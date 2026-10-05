// Leaflet map. The MapContainer is created once; data changes update layers in place (no re-mount, no flicker).
// Routes: the planned road route (blue, animated flow), the part already driven (green), origin/destination pins,
// trucks that glide smoothly between GPS updates, and the AI detour (orange).
import L from "leaflet";
import { Fragment, useEffect, useMemo, useRef } from "react";
import { CircleMarker, MapContainer, Marker, Polyline, Popup, TileLayer, Tooltip, useMap } from "react-leaflet";
import { useTranslation } from "react-i18next";

import { useTheme } from "@/lib/theme";
import { riskHex } from "@/lib/risk";
import type { Facility, OfflineSegment } from "@/lib/types";

type LL = [number, number];

export interface MapTruck {
  id: string;
  lat: number;
  lon: number;
  risk: number | null;
  label: string;
  sub?: string;
  offline?: boolean;
  onClick?: () => void;
  /** Fleet view: planned road route + endpoints for this truck. */
  route?: LL[] | null;
  origin?: LL | null;
  dest?: LL | null;
  originName?: string;
  destName?: string;
}
export interface Detour {
  facility: Facility;
  geometry: LL[] | null;
  label: string;
  recommended?: boolean;
  from: LL;
}

const icons = new Map<string, L.DivIcon>();
function truckIcon(color: string, offline: boolean): L.DivIcon {
  const key = `${color}|${offline}`;
  let icon = icons.get(key);
  if (!icon) {
    icon = L.divIcon({
      className: "truck-marker",
      html: `<span class="pulse" style="background:${color}55"></span><span style="position:relative;display:flex;align-items:center;justify-content:center;width:26px;height:26px;border-radius:9999px;background:${color};border:3px solid #fff;box-shadow:0 2px 6px #0007;font-size:13px;${offline ? "outline:2px dashed #64748b;outline-offset:2px" : ""}">🚚</span>`,
      iconSize: [26, 26],
      iconAnchor: [13, 13],
    });
    icons.set(key, icon);
  }
  return icon;
}
const pinIcon = (color: string, glyph: string) =>
  L.divIcon({
    className: "",
    html: `<div style="background:${color};color:#fff;border:2px solid #fff;border-radius:6px;padding:1px 6px;font:700 11px system-ui;box-shadow:0 1px 3px #0006;white-space:nowrap">${glyph}</div>`,
    iconSize: [26, 20],
    iconAnchor: [13, 10],
  });

function FitOnce({ points, resetKey }: { points: LL[]; resetKey: string }) {
  const map = useMap();
  const done = useRef<string | null>(null);
  useEffect(() => {
    if (points.length === 0 || done.current === resetKey) return;
    done.current = resetKey;
    if (points.length === 1) map.setView(points[0], 9);
    else map.fitBounds(L.latLngBounds(points), { padding: [32, 32], maxZoom: 11 });
  }, [map, points, resetKey]);
  return null;
}

/** Marker that glides to each new position instead of jumping (requestAnimationFrame, ~1.4 s ease-out). */
function GlideMarker({ pos, ...rest }: { pos: LL } & Omit<React.ComponentProps<typeof Marker>, "position">) {
  const ref = useRef<L.Marker | null>(null);
  const first = useRef<LL>(pos);
  const raf = useRef<number | null>(null);
  useEffect(() => {
    const m = ref.current;
    if (!m) return;
    const from = m.getLatLng();
    if (from.lat === pos[0] && from.lng === pos[1]) return;
    const reduce = typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    if (reduce) {
      m.setLatLng(pos);
      return;
    }
    const t0 = performance.now();
    const dur = 1400;
    const step = (now: number) => {
      const k = Math.min(1, (now - t0) / dur);
      const e = 1 - Math.pow(1 - k, 3);
      m.setLatLng([from.lat + (pos[0] - from.lat) * e, from.lng + (pos[1] - from.lng) * e]);
      if (k < 1) raf.current = requestAnimationFrame(step);
    };
    if (raf.current) cancelAnimationFrame(raf.current);
    raf.current = requestAnimationFrame(step);
    return () => {
      if (raf.current) cancelAnimationFrame(raf.current);
    };
  }, [pos[0], pos[1]]); // eslint-disable-line react-hooks/exhaustive-deps
  return <Marker ref={ref} position={first.current} {...rest} />;
}

/** Split a trail into normal and "offline stretch" parts (grey) using the offline segments' time ranges. */
export function splitTrail(
  gps: { t: number; lat: number; lon: number }[],
  offline: OfflineSegment[],
): { offline: boolean; pts: LL[] }[] {
  const out: { offline: boolean; pts: LL[] }[] = [];
  const isOff = (t: number) => offline.some((s) => t >= s.start && (s.end === null || t <= s.end));
  for (const p of gps) {
    const off = isOff(p.t);
    const last = out[out.length - 1];
    if (last && last.offline === off) last.pts.push([p.lat, p.lon]);
    else {
      // repeat the boundary point so the segments join
      const prev = last?.pts[last.pts.length - 1];
      out.push({ offline: off, pts: prev ? [prev, [p.lat, p.lon]] : [[p.lat, p.lon]] });
    }
  }
  return out;
}

/** Split a route at the vertex nearest to the truck: [already driven, still ahead]. */
export function splitRoute(route: LL[], pos: LL): [LL[], LL[]] {
  let best = 0;
  let bd = Infinity;
  route.forEach((p, i) => {
    const d = (p[0] - pos[0]) ** 2 + (p[1] - pos[1]) ** 2;
    if (d < bd) {
      bd = d;
      best = i;
    }
  });
  return [[...route.slice(0, best + 1), pos], [pos, ...route.slice(best + 1)]];
}

function RouteLayers({ route, pos, label }: { route: LL[]; pos?: LL | null; label?: string }) {
  const { resolved } = useTheme();
  const dark = resolved === "dark";
  const [done, ahead] = pos ? splitRoute(route, pos) : [[], route];
  return (
    <>
      <Polyline positions={route} pathOptions={{ color: dark ? "#0b1220" : "#ffffff", weight: 9, opacity: dark ? 0.9 : 0.85 }} interactive={false} />
      <Polyline positions={ahead} className="route-flow" pathOptions={{ color: dark ? "#60A5FA" : "#1F6FEB", weight: 5, opacity: 0.95 }}>
        {label && <Tooltip sticky>{label}</Tooltip>}
      </Polyline>
      {done.length > 1 && <Polyline positions={done} pathOptions={{ color: dark ? "#4ADE80" : "#2E7D32", weight: 6, opacity: 0.95 }} interactive={false} />}
    </>
  );
}

export function ShipmentMap({
  trucks,
  trail,
  offline = [],
  origin,
  dest,
  originName,
  destName,
  route,
  detour,
  alternatives = [],
  resetKey,
  height = 380,
  facilities = [],
}: {
  trucks: MapTruck[];
  trail?: { t: number; lat: number; lon: number }[];
  offline?: OfflineSegment[];
  origin?: LL | null;
  dest?: LL | null;
  originName?: string;
  destName?: string;
  route?: LL[] | null;
  detour?: Detour | null;
  alternatives?: Detour[];
  resetKey: string;
  height?: number;
  facilities?: Facility[];
}) {
  const { t } = useTranslation();
  const segments = useMemo(() => splitTrail(trail ?? [], offline), [trail, offline]);
  const fitPoints = useMemo(() => {
    const pts: LL[] = [];
    trucks.forEach((tr) => {
      pts.push([tr.lat, tr.lon]);
      if (trucks.length > 1) {
        if (tr.origin) pts.push(tr.origin);
        if (tr.dest) pts.push(tr.dest);
      }
    });
    if (origin) pts.push(origin);
    if (dest) pts.push(dest);
    if (detour) pts.push([detour.facility.lat, detour.facility.lng]);
    return pts;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [resetKey, trucks.length, trucks.map((x) => `${x.origin}|${x.dest}`).join(), origin?.[0], origin?.[1], dest?.[0], dest?.[1], detour?.facility.id]);

  const single = trucks.length === 1 ? trucks[0] : null;
  const planned = route ?? (origin && dest ? [origin, dest] : null);

  return (
    <div style={{ height }} className="overflow-hidden rounded-lg border" data-testid="shipment-map">
      <MapContainer center={[20.5, 77]} zoom={5} scrollWheelZoom={false} style={{ height: "100%", width: "100%" }}>
        <TileLayer attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors' url="https://tile.openstreetmap.org/{z}/{x}/{y}.png" />
        <FitOnce points={fitPoints} resetKey={resetKey} />

        {/* detail view: one planned route, the driven part comes from the GPS trail when we have it */}
        {planned && (
          <RouteLayers
            route={planned}
            pos={single && !(trail && trail.length > 1) ? [single.lat, single.lon] : null}
            label={originName && destName ? `${originName} → ${destName}` : undefined}
          />
        )}
        {origin && (
          <Marker position={origin} icon={pinIcon("#1F4E79", `A${originName ? " · " + originName : ""}`)}>
            <Tooltip>{originName ?? t("map.origin")}</Tooltip>
          </Marker>
        )}
        {dest && (
          <Marker position={dest} icon={pinIcon("#1F4E79", `B${destName ? " · " + destName : ""}`)}>
            <Tooltip>{destName ?? t("map.destination")}</Tooltip>
          </Marker>
        )}
        {segments.map((s, i) => (
          <Polyline
            key={i}
            positions={s.pts}
            pathOptions={s.offline ? { color: "#64748b", weight: 6, dashArray: "2 8", opacity: 0.95 } : { color: "#2E7D32", weight: 6, opacity: 0.95 }}
          />
        ))}

        {/* fleet view: every truck's planned route + endpoints */}
        {trucks.length > 1 &&
          trucks.map((tr) =>
            tr.route && tr.route.length > 1 ? (
              <RouteLayers key={`r-${tr.id}`} route={tr.route} pos={[tr.lat, tr.lon]} label={tr.originName && tr.destName ? `${tr.id}: ${tr.originName} → ${tr.destName}` : tr.id} />
            ) : null,
          )}
        {trucks.length > 1 &&
          trucks.map((tr) => (
            <Fragment key={`e-${tr.id}`}>
              {tr.origin && (
                <CircleMarker center={tr.origin} radius={5} pathOptions={{ color: "#fff", weight: 2, fillColor: "#1F4E79", fillOpacity: 1 }}>
                  <Tooltip>{tr.originName ?? t("map.origin")}</Tooltip>
                </CircleMarker>
              )}
              {tr.dest && (
                <CircleMarker center={tr.dest} radius={6} pathOptions={{ color: "#fff", weight: 2, fillColor: "#E87A1E", fillOpacity: 1 }}>
                  <Tooltip>{tr.destName ?? t("map.destination")}</Tooltip>
                </CircleMarker>
              )}
            </Fragment>
          ))}

        {facilities.map((f) => (
          <CircleMarker key={f.id} center={[f.lat, f.lng]} radius={4} pathOptions={{ color: "#1F4E79", weight: 1, fillOpacity: 0.5 }}>
            <Tooltip>{f.name}</Tooltip>
          </CircleMarker>
        ))}
        {alternatives.map((d) => (
          <DetourLayers key={d.facility.id} d={d} />
        ))}
        {detour && <DetourLayers d={detour} />}
        {trucks.map((tr) => (
          <GlideMarker
            key={tr.id}
            pos={[tr.lat, tr.lon]}
            icon={truckIcon(riskHex(tr.risk), !!tr.offline)}
            eventHandlers={tr.onClick ? { click: tr.onClick } : undefined}
            keyboard
            title={tr.label}
            zIndexOffset={1000}
          >
            <Popup>
              <strong>{tr.label}</strong>
              {tr.sub && <div>{tr.sub}</div>}
            </Popup>
          </GlideMarker>
        ))}
      </MapContainer>
    </div>
  );
}

function DetourLayers({ d }: { d: Detour }) {
  const line = d.geometry ?? [d.from, [d.facility.lat, d.facility.lng] as LL];
  return (
    <>
      <Polyline positions={line} pathOptions={{ color: d.recommended ? "#E87A1E" : "#94a3b8", weight: d.recommended ? 6 : 3, dashArray: d.recommended ? undefined : "4 6", opacity: 0.95 }} className={d.recommended ? "route-flow-fast" : undefined} />
      <Marker position={[d.facility.lat, d.facility.lng]} icon={pinIcon(d.recommended ? "#E87A1E" : "#64748b", d.recommended ? "★" : "•")}>
        <Tooltip permanent={d.recommended} direction="top">{d.label}</Tooltip>
      </Marker>
    </>
  );
}
