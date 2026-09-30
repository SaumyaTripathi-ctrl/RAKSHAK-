// Leaflet map. The MapContainer is created once; data changes update layers in place (no re-mount, no flicker).
import L from "leaflet";
import { useEffect, useMemo, useRef } from "react";
import { CircleMarker, MapContainer, Marker, Polyline, Popup, TileLayer, Tooltip, useMap } from "react-leaflet";
import { useTranslation } from "react-i18next";

import { riskHex } from "@/lib/risk";
import type { Facility, OfflineSegment } from "@/lib/types";

export interface MapTruck {
  id: string;
  lat: number;
  lon: number;
  risk: number | null;
  label: string;
  sub?: string;
  offline?: boolean;
  onClick?: () => void;
}
export interface Detour {
  facility: Facility;
  geometry: [number, number][] | null;
  label: string;
  recommended?: boolean;
  from: [number, number];
}

const icons = new Map<string, L.DivIcon>();
function truckIcon(color: string, offline: boolean): L.DivIcon {
  const key = `${color}|${offline}`;
  let icon = icons.get(key);
  if (!icon) {
    icon = L.divIcon({
      className: "truck-marker",
      html: `<span class="pulse" style="background:${color}55"></span><span style="position:relative;display:block;width:22px;height:22px;border-radius:9999px;background:${color};border:3px solid #fff;box-shadow:0 1px 4px #0006;${offline ? "outline:2px dashed #64748b;outline-offset:2px" : ""}"></span>`,
      iconSize: [22, 22],
      iconAnchor: [11, 11],
    });
    icons.set(key, icon);
  }
  return icon;
}
const pinIcon = (color: string, glyph: string) =>
  L.divIcon({
    className: "",
    html: `<div style="background:${color};color:#fff;border:2px solid #fff;border-radius:6px;padding:1px 5px;font:700 11px system-ui;box-shadow:0 1px 3px #0006">${glyph}</div>`,
    iconSize: [26, 20],
    iconAnchor: [13, 10],
  });

function FitOnce({ points, resetKey }: { points: [number, number][]; resetKey: string }) {
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

/** Split a trail into normal and "offline stretch" parts (grey) using the offline segments' time ranges. */
export function splitTrail(
  gps: { t: number; lat: number; lon: number }[],
  offline: OfflineSegment[],
): { offline: boolean; pts: [number, number][] }[] {
  const out: { offline: boolean; pts: [number, number][] }[] = [];
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

export function ShipmentMap({
  trucks,
  trail,
  offline = [],
  origin,
  dest,
  detour,
  alternatives = [],
  resetKey,
  height = 380,
  facilities = [],
}: {
  trucks: MapTruck[];
  trail?: { t: number; lat: number; lon: number }[];
  offline?: OfflineSegment[];
  origin?: [number, number] | null;
  dest?: [number, number] | null;
  detour?: Detour | null;
  alternatives?: Detour[];
  resetKey: string;
  height?: number;
  facilities?: Facility[];
}) {
  const { t } = useTranslation();
  const segments = useMemo(() => splitTrail(trail ?? [], offline), [trail, offline]);
  const fitPoints = useMemo(() => {
    const pts: [number, number][] = [];
    trucks.forEach((tr) => pts.push([tr.lat, tr.lon]));
    if (origin) pts.push(origin);
    if (dest) pts.push(dest);
    if (detour) pts.push([detour.facility.lat, detour.facility.lng]);
    return pts;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [resetKey, trucks.length, origin?.[0], origin?.[1], dest?.[0], dest?.[1], detour?.facility.id]);

  return (
    <div style={{ height }} className="overflow-hidden rounded-lg border" data-testid="shipment-map">
      <MapContainer center={[20.5, 77]} zoom={5} scrollWheelZoom={false} style={{ height: "100%", width: "100%" }}>
        <TileLayer attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors' url="https://tile.openstreetmap.org/{z}/{x}/{y}.png" />
        <FitOnce points={fitPoints} resetKey={resetKey} />
        {origin && dest && <Polyline positions={[origin, dest]} pathOptions={{ color: "#1F4E79", weight: 2, dashArray: "6 8", opacity: 0.6 }} />}
        {origin && <Marker position={origin} icon={pinIcon("#1F4E79", "A")}><Tooltip>{t("map.origin")}</Tooltip></Marker>}
        {dest && <Marker position={dest} icon={pinIcon("#1F4E79", "B")}><Tooltip>{t("map.destination")}</Tooltip></Marker>}
        {segments.map((s, i) => (
          <Polyline
            key={i}
            positions={s.pts}
            pathOptions={s.offline ? { color: "#64748b", weight: 5, dashArray: "2 8", opacity: 0.9 } : { color: "#2E7D32", weight: 4, opacity: 0.85 }}
          />
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
          <Marker
            key={tr.id}
            position={[tr.lat, tr.lon]}
            icon={truckIcon(riskHex(tr.risk), !!tr.offline)}
            eventHandlers={tr.onClick ? { click: tr.onClick } : undefined}
            keyboard
            title={tr.label}
          >
            <Popup>
              <strong>{tr.label}</strong>
              {tr.sub && <div>{tr.sub}</div>}
            </Popup>
          </Marker>
        ))}
      </MapContainer>
    </div>
  );
}

function DetourLayers({ d }: { d: Detour }) {
  const line = d.geometry ?? [d.from, [d.facility.lat, d.facility.lng]];
  return (
    <>
      <Polyline positions={line} pathOptions={{ color: d.recommended ? "#E87A1E" : "#94a3b8", weight: d.recommended ? 5 : 3, dashArray: d.recommended ? undefined : "4 6", opacity: 0.9 }} />
      <Marker position={[d.facility.lat, d.facility.lng]} icon={pinIcon(d.recommended ? "#E87A1E" : "#64748b", d.recommended ? "★" : "•")}>
        <Tooltip permanent={d.recommended} direction="top">{d.label}</Tooltip>
      </Marker>
    </>
  );
}
