import { AlertOctagon, BellOff, Check, MapPin, RefreshCw } from "lucide-react";
import { useEffect, useMemo } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate, useParams } from "react-router-dom";

import { LevelBadge } from "@/components/badges";
import { EventFeed } from "@/components/EventFeed";
import { ShipmentMap, type Detour } from "@/components/ShipmentMap";
import { ShipmentPicker } from "@/components/ShipmentPicker";
import { EmptyState, ErrorState, LoadingBlock } from "@/components/States";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useAuth } from "@/lib/auth";
import { formatDuration } from "@/lib/format";
import {
  useAcceptReroute,
  useAckEvent,
  useEvents,
  useFleet,
  useLive,
  useRefreshReroute,
  useReroute,
  useShipment,
  useTimeline,
} from "@/lib/queries";
import type { RerouteOption } from "@/lib/types";

export default function Alerts() {
  const { id } = useParams();
  const nav = useNavigate();
  const { t } = useTranslation();
  const fleet = useFleet();

  // Default to the most endangered active shipment.
  const worst = useMemo(() => {
    const trucks = [...(fleet.data?.trucks ?? [])];
    trucks.sort((a, b) => (b.risk?.risk ?? b.level * 40) - (a.risk?.risk ?? a.level * 40));
    return trucks[0]?.shipment_id;
  }, [fleet.data]);
  const current = id ?? worst;
  useEffect(() => {
    if (!id && worst) nav(`/alerts/${worst}`, { replace: true });
  }, [id, worst, nav]);

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-2xl font-bold tracking-tight">{t("alerts.title")}</h1>
        <ShipmentPicker value={current} onChange={(v) => nav(`/alerts/${v}`)} />
      </div>
      {current ? <Emergency id={current} /> : <EmptyState title={t("alerts.pick")} />}
    </div>
  );
}

function OptionRow({ o, recommended, accepted, onAccept, busy, canAccept }: { o: RerouteOption; recommended: boolean; accepted: boolean; onAccept: () => void; busy: boolean; canAccept: boolean }) {
  const { t } = useTranslation();
  const estimate = o.routing_source !== "osrm";
  return (
    <li className={`rounded-lg border p-3 ${recommended ? "border-orange-500/70 bg-orange-50 dark:bg-orange-950/30" : ""}`} data-recommended={recommended}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <p className="font-semibold">
            {recommended && <Badge variant="warn" className="mr-2">★ {t("alerts.recommended")}</Badge>}
            {o.facility.name}
          </p>
          <p className="text-sm text-muted-foreground">
            {t(`facility.${o.facility.type}`, { defaultValue: o.facility.type })} · {o.facility.town}, {o.facility.state} · {o.facility.storage_min}–{o.facility.storage_max} °C ·{" "}
            {t("alerts.freeRoom", { t: o.facility.free_tonnes })}
          </p>
        </div>
        <div className="text-right text-sm">
          <p className="text-lg font-bold tabular-nums">{formatDuration(o.duration_min / 60)}</p>
          <p className="tabular-nums text-muted-foreground">{o.distance_km} km</p>
        </div>
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-2 text-xs">
        <Badge variant={estimate ? "warn" : "safe"}>{estimate ? t("alerts.estimate") : t("alerts.roadRoute")}</Badge>
        {o.reachable_before_spoilage === true && <Badge variant="safe">{t("alerts.reachable")}</Badge>}
        {o.reachable_before_spoilage === false && <Badge variant="crit">{t("alerts.notReachable")}</Badge>}
        <Badge variant="sim" title={t("alerts.syntheticHint")}>{o.facility.data_source}</Badge>
        {canAccept && (
          <Button size="sm" className="ml-auto" variant={recommended ? "accent" : "outline"} disabled={busy || accepted} onClick={onAccept}>
            {accepted ? <><Check /> {t("alerts.accepted")}</> : t("alerts.accept")}
          </Button>
        )}
      </div>
    </li>
  );
}

function Emergency({ id }: { id: string }) {
  const { t } = useTranslation();
  const { can } = useAuth();
  const shipment = useShipment(id);
  const live = useLive(id);
  const timeline = useTimeline(id);
  const events = useEvents(id);
  const ack = useAckEvent();
  const accept = useAcceptReroute(id);
  const refresh = useRefreshReroute(id);
  const r = live.data?.risk;
  const hasPos = live.data?.hub?.lat != null;
  const reroute = useReroute(id, hasPos);

  const origin = hasPos ? ([live.data!.hub!.lat!, live.data!.hub!.lon!] as [number, number]) : null;
  const doc = reroute.data;
  const accepted = doc?.accepted_facility_id ?? (r?.reroute?.accepted ? r.reroute.facility_id : null);
  const s = shipment.data;

  const detours = useMemo(() => {
    if (!doc || !origin) return { main: null as Detour | null, alts: [] as Detour[] };
    const mk = (o: RerouteOption, recommended: boolean): Detour => ({ facility: o.facility, geometry: o.geometry ?? null, label: `${o.facility.name}`, recommended, from: origin });
    return { main: doc.recommended ? mk(doc.recommended, true) : null, alts: doc.alternatives.map((a) => mk(a, false)) };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [doc, origin?.[0], origin?.[1]]);

  if (live.isPending || shipment.isPending) return <LoadingBlock rows={3} />;
  if (live.isError) return <ErrorState error={live.error} onRetry={() => void live.refetch()} />;

  const critical = r?.level === "CRITICAL";
  const unackedCritical = (events.data ?? []).find((e) => e.kind === "ALERT_CRITICAL" && !e.acknowledged_at);

  return (
    <div className="space-y-5">
      <Card className={critical ? "border-red-600/60 bg-red-50 dark:bg-red-950/30" : r?.level === "WARNING" ? "border-orange-500/60" : ""} role="region" aria-label={t("alerts.emergency")}>
        <CardContent className="flex flex-wrap items-center gap-4 p-4 sm:p-5">
          <AlertOctagon className={`size-10 ${critical ? "text-red-600" : r?.level === "WARNING" ? "text-orange-500" : "text-green-600"}`} aria-hidden />
          <div className="min-w-0 flex-1">
            <p className="flex flex-wrap items-center gap-2 text-lg font-bold">
              {id} <LevelBadge level={r?.level ?? "SAFE"} latched={r?.latched} />
            </p>
            {r ? (
              <>
                <p className="text-sm">
                  {t("alerts.riskLine", { risk: Math.round(r.risk), life: formatDuration(r.rsl_hours) })}
                </p>
                <ul className="mt-1 list-inside list-disc text-sm text-muted-foreground">
                  {r.drivers.slice(0, 3).map((d, i) => (
                    <li key={i}>{d.text}</li>
                  ))}
                </ul>
              </>
            ) : (
              <p className="text-sm text-muted-foreground">{t("cards.noPrediction")}</p>
            )}
          </div>
          {unackedCritical && can("admin", "fpo", "driver") && (
            <Button variant="destructive" disabled={ack.isPending} onClick={() => ack.mutate(unackedCritical.id)}>
              <BellOff /> {t("alerts.silence")}
            </Button>
          )}
        </CardContent>
      </Card>

      <div className="grid gap-5 xl:grid-cols-5">
        <Card className="xl:col-span-2">
          <CardHeader className="flex-row items-center justify-between">
            <CardTitle className="flex items-center gap-2">
              <MapPin className="size-4" aria-hidden /> {t("alerts.detour")}
            </CardTitle>
            {can("admin", "fpo", "driver") && (
              <Button size="sm" variant="ghost" disabled={refresh.isPending || !hasPos} onClick={() => refresh.mutate()}>
                <RefreshCw /> {t("alerts.recompute")}
              </Button>
            )}
          </CardHeader>
          <CardContent className="space-y-3">
            {!hasPos ? (
              <EmptyState title={t("alerts.noPosition")} />
            ) : reroute.isPending ? (
              <LoadingBlock rows={2} />
            ) : reroute.isError ? (
              <ErrorState error={reroute.error} onRetry={() => void reroute.refetch()} />
            ) : !doc?.recommended ? (
              <EmptyState title={t("alerts.noFacility")} hint={doc?.reason} />
            ) : (
              <>
                <p className="text-xs text-muted-foreground">{doc.reason}</p>
                <ul className="space-y-2">
                  <OptionRow o={doc.recommended} recommended accepted={accepted === doc.recommended.facility.id} busy={accept.isPending} canAccept={can("admin", "fpo", "driver")} onAccept={() => accept.mutate(doc.recommended!.facility.id)} />
                  {doc.alternatives.map((a) => (
                    <OptionRow key={a.facility.id} o={a} recommended={false} accepted={accepted === a.facility.id} busy={accept.isPending} canAccept={can("admin", "fpo", "driver")} onAccept={() => accept.mutate(a.facility.id)} />
                  ))}
                </ul>
                {accept.isError && <p role="alert" className="text-sm text-destructive">{accept.error.message}</p>}
              </>
            )}
          </CardContent>
        </Card>

        <Card className="xl:col-span-3">
          <CardHeader>
            <CardTitle>{t("map.title")}</CardTitle>
          </CardHeader>
          <CardContent>
            <ShipmentMap
              resetKey={`alert-${id}-${detours.main?.facility.id ?? "none"}`}
              height={440}
              trucks={origin ? [{ id, lat: origin[0], lon: origin[1], risk: r?.risk ?? null, label: id, offline: live.data?.sync.online === false }] : []}
              trail={timeline.data?.gps}
              offline={timeline.data?.offline_segments}
              origin={s?.origin_lat != null && s.origin_lon != null ? [s.origin_lat, s.origin_lon] : null}
              dest={s?.dest_lat != null && s.dest_lon != null ? [s.dest_lat, s.dest_lon] : null}
              detour={detours.main}
              alternatives={detours.alts}
            />
            <p className="mt-2 text-xs text-muted-foreground">{t("alerts.mapHint")}</p>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>{t("fleet.alertFeed")}</CardTitle>
        </CardHeader>
        <CardContent>
          {events.isPending ? <LoadingBlock rows={3} /> : events.isError ? <ErrorState error={events.error} /> : events.data.length === 0 ? <EmptyState title={t("fleet.noAlerts")} /> : <EventFeed events={events.data} showShipment={false} limit={40} />}
        </CardContent>
      </Card>
    </div>
  );
}
