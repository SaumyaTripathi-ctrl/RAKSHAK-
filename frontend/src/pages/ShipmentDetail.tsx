import {
  Battery,
  BatteryLow,
  Droplets,
  FlaskConical,
  Gauge,
  Hourglass,
  Thermometer,
  Fan,
  PanelTopOpen,
  Waves,
  Zap,
} from "lucide-react";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { Link, useParams } from "react-router-dom";

import { LevelBadge, SyncBadge } from "@/components/badges";
import { EventFeed } from "@/components/EventFeed";
import { RiskGauge } from "@/components/RiskGauge";
import { ShipmentMap, type Detour, type MapTruck } from "@/components/ShipmentMap";
import { EmptyState, ErrorState, LoadingBlock, SimulatedBadge } from "@/components/States";
import { StatCard, type Tone } from "@/components/StatCard";
import { TrendChart, type SeriesDef } from "@/components/TrendChart";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { TBody, TD, TH, THead, TR, Table } from "@/components/ui/misc";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useAuth } from "@/lib/auth";
import { fmt, formatDateTime, formatDuration, humanFood, timeAgo } from "@/lib/format";
import {
  useEvents,
  useFoodTypes,
  useLive,
  useReroute,
  useRiskHistory,
  useSendCommand,
  useShipment,
  useTimeline,
} from "@/lib/queries";
import { LEVEL_STYLES, levelFromCode, riskHex } from "@/lib/risk";
import type { Live, LiveTag, RiskPointDto, Timeline } from "@/lib/types";

const TAG_COLORS = ["#1F4E79", "#2E7D32", "#7B1FA2", "#00838F", "#6D4C41", "#AD1457"];

function tagSeries(tl: Timeline | undefined, pick: (p: Timeline["tags"][string][number]) => number | null): SeriesDef[] {
  if (!tl) return [];
  return Object.entries(tl.tags).map(([id, pts], i) => ({
    key: id,
    label: id,
    color: TAG_COLORS[i % TAG_COLORS.length],
    width: 1.6,
    points: pts.map((p) => ({ t: p.t, v: pick(p) })),
  }));
}

function minBattery(live: Live): number | null {
  const v = [live.hub?.battery_pct, ...live.tags.map((t) => t.battery_pct)].filter((x): x is number => x !== null && x !== undefined);
  return v.length ? Math.min(...v) : null;
}

export default function ShipmentDetail() {
  const { id = "" } = useParams();
  const { t } = useTranslation();
  const { can } = useAuth();
  const shipment = useShipment(id);
  const live = useLive(id);
  const timeline = useTimeline(id);
  const risk = useRiskHistory(id);
  const events = useEvents(id);
  const foods = useFoodTypes();
  const band = foods.data?.find((f) => f.food_type === shipment.data?.food_type);
  const risky = live.data?.risk?.level === "CRITICAL" || !!live.data?.risk?.reroute;
  const reroute = useReroute(id, risky);

  const detours = useMemo<{ main: Detour | null; alts: Detour[] }>(() => {
    const doc = reroute.data;
    const origin = live.data?.hub?.lat != null && live.data.hub.lon != null ? ([live.data.hub.lat, live.data.hub.lon] as [number, number]) : null;
    if (!doc || !origin) return { main: null, alts: [] };
    const mk = (o: NonNullable<typeof doc.recommended>, recommended: boolean): Detour => ({
      facility: o.facility,
      geometry: o.geometry ?? null,
      label: `${o.facility.name} · ${o.distance_km} km`,
      recommended,
      from: origin,
    });
    return { main: doc.recommended ? mk(doc.recommended, true) : null, alts: doc.alternatives.map((a) => mk(a, false)) };
  }, [reroute.data, live.data?.hub?.lat, live.data?.hub?.lon]);

  if (shipment.isPending || live.isPending) return <LoadingBlock rows={4} />;
  if (shipment.isError) return <ErrorState error={shipment.error} onRetry={() => void shipment.refetch()} />;
  if (live.isError) return <ErrorState error={live.error} onRetry={() => void live.refetch()} />;

  const s = shipment.data;
  const lv = live.data;
  const r = lv.risk;
  const level = r?.level ?? levelFromCode(lv.hub?.alert_level);
  const hub = lv.hub;
  const batt = minBattery(lv);
  const tl = timeline.data;
  const lowBatt = batt !== null && batt < 20;
  const trucks: MapTruck[] =
    hub?.lat != null && hub.lon != null
      ? [{ id: s.id, lat: hub.lat, lon: hub.lon, risk: r?.risk ?? (level === "SAFE" ? 10 : level === "WARNING" ? 50 : 80), label: s.id, sub: `${fmt(lv.aggregates.temp_c, 1, " °C")}`, offline: lv.sync.online === false }]
      : [];
  const tone = (l: string): Tone => (l === "CRITICAL" ? "crit" : l === "WARNING" ? "warn" : "safe");

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="flex flex-wrap items-center gap-2 text-2xl font-bold tracking-tight">
            {s.id}
            <LevelBadge level={level} latched={r?.latched} />
            {s.model_profile === "demo" && <SimulatedBadge label={t("shipment.demoModel")} />}
          </h1>
          <p className="text-sm text-muted-foreground">
            {t(`foods.${s.food_type}`, { defaultValue: humanFood(s.food_type) })}
            {s.variety ? ` · ${s.variety}` : ""} · {s.weight_kg} kg · {s.origin_name || "?"} → {s.dest_name || "?"} ·{" "}
            <Badge variant="muted">{t(`status.${s.status}`)}</Badge>
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button asChild variant="outline" size="sm">
            <Link to={`/custody/${s.id}`}>{t("nav.custody")}</Link>
          </Button>
          <Button asChild variant="outline" size="sm">
            <Link to={`/verify/${s.id}`}>{t("nav.verify")}</Link>
          </Button>
          <Button asChild variant="outline" size="sm">
            <Link to={`/alerts/${s.id}`}>{t("nav.alerts")}</Link>
          </Button>
          <Button asChild variant="secondary" size="sm">
            <a href={`/p/${s.id}`} target="_blank" rel="noreferrer">
              {t("shipment.publicPage")}
            </a>
          </Button>
        </div>
      </div>

      {r?.latched && r.level !== "CRITICAL" && <p className="text-sm text-muted-foreground">{t("alerts.latchedHint")}</p>}

      <section aria-label={t("shipment.liveCards")} className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-5">
        <StatCard icon={Thermometer} label={t("cards.temperature")} value={fmt(lv.aggregates.temp_c, 1)} unit="°C" sub={band ? t("cards.band", { min: band.min_temp, max: band.max_temp }) : undefined}
          tone={band && lv.aggregates.temp_c != null ? (lv.aggregates.temp_c > band.max_temp || lv.aggregates.temp_c < band.min_temp ? "warn" : "safe") : "default"} />
        <StatCard icon={Droplets} label={t("cards.humidity")} value={fmt(lv.aggregates.rh_pct, 0)} unit="%" sub={band && band.max_rh - band.min_rh < 50 ? t("cards.band", { min: band.min_rh, max: band.max_rh }) : undefined} />
        <StatCard icon={Waves} label={t("cards.ethylene")} value={fmt(lv.aggregates.ethylene_idx, 0)} unit="%" sub={t("cards.ethyleneHint")}
          tone={(lv.aggregates.ethylene_idx ?? 0) >= 70 ? "crit" : (lv.aggregates.ethylene_idx ?? 0) >= 40 ? "warn" : "default"} />
        <StatCard icon={Zap} label={t("cards.shock")} value={fmt(hub?.shock_g ?? null, 2)} unit="g" tone={(hub?.shock_g ?? 0) >= 1 ? "warn" : "default"} />
        <StatCard icon={PanelTopOpen} label={t("cards.flap")} value={hub?.flap_pct ?? "-"} unit="%" sub={t("cards.flapHint")}>
          <div className="mt-2 h-2 overflow-hidden rounded-full bg-muted" aria-hidden>
            <div className="h-full bg-secondary transition-all" style={{ width: `${hub?.flap_pct ?? 0}%` }} />
          </div>
        </StatCard>
        <StatCard icon={Fan} label={t("cards.fan")} value={hub?.fan_on ? t("common.on") : t("common.off")} tone={hub?.fan_on ? "safe" : "default"} sub={t("cards.fanHint")} />
        <StatCard icon={lowBatt ? BatteryLow : Battery} label={t("cards.battery")} value={batt ?? "-"} unit="%" tone={lowBatt ? "warn" : "default"} sub={t("cards.batteryHint")} />
        <StatCard label={t("cards.sync")}>
          <div className="mt-2">
            <SyncBadge online={lv.sync.online} backlog={lv.sync.backlog} offlineSince={lv.sync.offline_since} />
          </div>
          <p className="mt-2 text-xs text-muted-foreground">
            {t("cards.backlog", { count: lv.sync.backlog })} · {t("cards.lastSeen", { when: timeAgo(hub?.last_seen_at) })}
          </p>
        </StatCard>

        <Card className="col-span-2 row-span-2 p-4 md:col-span-2 xl:col-span-2">
          <div className="flex items-center justify-between text-sm text-muted-foreground">
            <span className="font-medium">{t("cards.risk")}</span>
            <Gauge className="size-4" aria-hidden />
          </div>
          <div className="mx-auto max-w-[260px]">
            <RiskGauge risk={r?.risk ?? null} />
          </div>
          <div className="flex items-center justify-center gap-2">
            <LevelBadge level={level} latched={r?.latched} />
            {r && <span className="text-xs text-muted-foreground">{t("cards.modelProfile", { profile: t(`shipment.profile_${r.model_profile}`) })}</span>}
          </div>
          {r ? (
            <>
              <p className="mt-2 flex items-center justify-center gap-1 text-center text-xs text-muted-foreground">
                <FlaskConical className="size-3.5" aria-hidden /> {t("cards.simulatedModel")}
              </p>
              {r.drivers.length > 0 && (
                <ul className="mt-3 space-y-1 text-sm">
                  {r.drivers.map((d, i) => (
                    <li key={i} className="flex gap-2">
                      <span className={`mt-1.5 size-2 shrink-0 rounded-full ${d.severity >= 3 ? "bg-red-600" : d.severity === 2 ? "bg-orange-500" : d.severity === 1 ? "bg-yellow-500" : "bg-slate-400"}`} aria-hidden />
                      {d.text}
                    </li>
                  ))}
                </ul>
              )}
            </>
          ) : (
            <p className="mt-2 text-center text-sm text-muted-foreground">{t("cards.noPrediction")}</p>
          )}
        </Card>

        <StatCard icon={Hourglass} label={t("cards.safeLife")} tone={r ? tone(r.level) : "default"} className="col-span-2 md:col-span-1 xl:col-span-2">
          <p className="mt-1 text-3xl font-bold tabular-nums tracking-tight" aria-live="polite" data-testid="safe-life">
            {r ? formatDuration(r.rsl_hours) : "-"}
          </p>
          {r && (
            <div className="mt-2 h-2 overflow-hidden rounded-full bg-muted" aria-hidden>
              <div className="h-full transition-all" style={{ width: `${Math.min(100, (r.rsl_hours / (r.model_profile === "demo" ? 10 : 240)) * 100)}%`, background: riskHex(r.risk) }} />
            </div>
          )}
          <p className="mt-1 text-xs text-muted-foreground">{t("cards.safeLifeHint")}</p>
        </StatCard>
      </section>

      {r?.reroute && (
        <Card className="border-orange-500/60 bg-orange-50 dark:bg-orange-950/30">
          <CardContent className="flex flex-wrap items-center gap-3 p-4">
            <span className="font-semibold">{t("alerts.rerouteBanner", { name: r.reroute.facility })}</span>
            <span className="text-sm text-muted-foreground">
              {r.reroute.distance_km} km · {formatDuration(r.reroute.duration_min / 60)}
              {r.reroute.accepted ? ` · ${t("alerts.accepted")}` : ""}
            </span>
            <Button asChild size="sm" className="ml-auto" variant="accent">
              <Link to={`/alerts/${s.id}`}>{t("alerts.openEmergency")}</Link>
            </Button>
          </CardContent>
        </Card>
      )}

      <div className="grid gap-5 xl:grid-cols-5">
        <Card className="xl:col-span-3">
          <CardHeader>
            <CardTitle>{t("charts.title")}</CardTitle>
          </CardHeader>
          <CardContent>
            {timeline.isPending ? (
              <LoadingBlock rows={2} />
            ) : timeline.isError ? (
              <ErrorState error={timeline.error} onRetry={() => void timeline.refetch()} />
            ) : (
              <Tabs defaultValue="temp">
                <TabsList>
                  <TabsTrigger value="temp">{t("cards.temperature")}</TabsTrigger>
                  <TabsTrigger value="rh">{t("cards.humidity")}</TabsTrigger>
                  <TabsTrigger value="eth">{t("cards.ethylene")}</TabsTrigger>
                  <TabsTrigger value="risk">{t("cards.risk")}</TabsTrigger>
                  <TabsTrigger value="act">{t("charts.actuators")}</TabsTrigger>
                </TabsList>
                <TabsContent value="temp">
                  <TrendChart
                    unit="°"
                    offline={tl?.offline_segments}
                    band={band ? { min: band.min_temp, max: band.max_temp, label: t("charts.safeBand") } : undefined}
                    series={[
                      ...tagSeries(tl, (p) => p.temp_c),
                      { key: "hub", label: t("charts.ambient"), color: "#94a3b8", dashed: true, width: 1.4, points: (tl?.hub ?? []).map((p) => ({ t: p.t, v: p.temp_c })) },
                    ]}
                  />
                </TabsContent>
                <TabsContent value="rh">
                  <TrendChart unit="%" offline={tl?.offline_segments} band={band && band.max_rh - band.min_rh < 50 ? { min: band.min_rh, max: band.max_rh, label: t("charts.safeBand") } : undefined} series={tagSeries(tl, (p) => p.rh_pct)} yDomain={[0, 100]} />
                </TabsContent>
                <TabsContent value="eth">
                  <TrendChart unit="%" offline={tl?.offline_segments} series={tagSeries(tl, (p) => p.ethylene_idx)} yDomain={[0, 100]} />
                </TabsContent>
                <TabsContent value="risk">
                  <RiskChart points={risk.data?.points ?? []} offline={tl?.offline_segments ?? []} />
                </TabsContent>
                <TabsContent value="act">
                  <TrendChart
                    offline={tl?.offline_segments}
                    yDomain={[0, 100]}
                    series={[
                      { key: "flap", label: t("cards.flap"), color: "#1F4E79", step: true, points: (tl?.hub ?? []).map((p) => ({ t: p.t, v: p.flap_pct })) },
                      { key: "fan", label: t("cards.fan"), color: "#2E7D32", step: true, points: (tl?.hub ?? []).map((p) => ({ t: p.t, v: p.fan_on ? 100 : 0 })) },
                      { key: "shock", label: t("cards.shock") + " ×10", color: "#E87A1E", width: 1.4, points: (tl?.hub ?? []).map((p) => ({ t: p.t, v: p.shock_g === null ? null : Math.min(100, p.shock_g * 10) })) },
                    ]}
                  />
                </TabsContent>
              </Tabs>
            )}
            <p className="mt-2 text-xs text-muted-foreground">{t("charts.offlineHint")}</p>
          </CardContent>
        </Card>

        <Card className="xl:col-span-2">
          <CardHeader>
            <CardTitle>{t("map.title")}</CardTitle>
          </CardHeader>
          <CardContent>
            <ShipmentMap
              resetKey={s.id}
              height={320}
              trucks={trucks}
              trail={tl?.gps}
              offline={tl?.offline_segments}
              origin={s.origin_lat != null && s.origin_lon != null ? [s.origin_lat, s.origin_lon] : null}
              dest={s.dest_lat != null && s.dest_lon != null ? [s.dest_lat, s.dest_lon] : null}
              detour={detours.main}
              alternatives={detours.alts}
            />
            <p className="mt-2 text-xs text-muted-foreground">{t("map.legend")}</p>
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-5 xl:grid-cols-5">
        <Card className="xl:col-span-3">
          <CardHeader>
            <CardTitle>{t("tags.title")}</CardTitle>
          </CardHeader>
          <CardContent>
            {lv.tags.length === 0 ? <EmptyState title={t("tags.none")} /> : <TagTable tags={lv.tags} />}
          </CardContent>
        </Card>
        <div className="space-y-5 xl:col-span-2">
          {can("admin", "fpo", "driver") && hub && <CommandPanel hub={hub.device_id} shipment={s.id} floor={hub.flap_pct ?? 0} />}
          <Card>
            <CardHeader>
              <CardTitle>{t("fleet.alertFeed")}</CardTitle>
            </CardHeader>
            <CardContent>
              {events.isPending ? <LoadingBlock rows={3} /> : events.isError ? <ErrorState error={events.error} /> : events.data.length === 0 ? <EmptyState title={t("fleet.noAlerts")} /> : <EventFeed events={events.data} showShipment={false} limit={15} />}
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}

function TagTable({ tags }: { tags: LiveTag[] }) {
  const { t } = useTranslation();
  return (
    <Table>
      <THead>
        <TR>
          <TH>{t("tags.tag")}</TH>
          <TH>{t("cards.temperature")}</TH>
          <TH>{t("cards.humidity")}</TH>
          <TH>{t("cards.ethylene")}</TH>
          <TH>{t("tags.lid")}</TH>
          <TH>{t("cards.battery")}</TH>
          <TH>{t("devices.lastSeen")}</TH>
        </TR>
      </THead>
      <TBody>
        {tags.map((g) => (
          <TR key={g.device_id}>
            <TD className="font-medium">{g.device_id}</TD>
            <TD className="tabular-nums">{fmt(g.temp_c, 1, " °C")}</TD>
            <TD className="tabular-nums">{fmt(g.rh_pct, 0, "%")}</TD>
            <TD className="tabular-nums">{fmt(g.ethylene_idx, 0, "%")}</TD>
            <TD>{g.lid_open ? <Badge variant="crit">{t("tags.opened")}</Badge> : <Badge variant="safe">{t("tags.closed")}</Badge>}</TD>
            <TD className="tabular-nums">{g.battery_pct ?? "-"}%</TD>
            <TD className="whitespace-nowrap text-muted-foreground">{formatDateTime(g.time_utc)}</TD>
          </TR>
        ))}
      </TBody>
    </Table>
  );
}

function RiskChart({ points, offline }: { points: RiskPointDto[]; offline: Timeline["offline_segments"] }) {
  const { t } = useTranslation();
  const series: SeriesDef[] = [
    { key: "risk", label: t("cards.risk"), color: "#C62828", width: 2.4, points: points.map((p) => ({ t: p.t, v: p.risk })) },
    { key: "w", label: t("levels.WARNING"), color: LEVEL_STYLES.WARNING.hex, dashed: true, width: 1, points: points.map((p) => ({ t: p.t, v: 30 })) },
    { key: "c", label: t("levels.CRITICAL"), color: LEVEL_STYLES.CRITICAL.hex, dashed: true, width: 1, points: points.map((p) => ({ t: p.t, v: 70 })) },
  ];
  return <TrendChart series={series} offline={offline} yDomain={[0, 100]} />;
}

function CommandPanel({ hub, shipment, floor }: { hub: string; shipment: string; floor: number }) {
  const { t } = useTranslation();
  const send = useSendCommand();
  const run = (cmd: string, arg?: number) => send.mutate({ hub, cmd, arg: arg ?? null, shipment_id: shipment });
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("commands.title")}</CardTitle>
        <p className="text-xs text-muted-foreground">{t("commands.hint")}</p>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex flex-wrap gap-2" role="group" aria-label={t("commands.flap")}>
          {[0, 25, 50, 100].map((v) => (
            <Button key={v} size="sm" variant={floor === v ? "secondary" : "outline"} disabled={send.isPending} onClick={() => run("FLAP_SET", v)}>
              {t("commands.flapTo", { pct: v })}
            </Button>
          ))}
        </div>
        <div className="flex flex-wrap gap-2">
          <Button size="sm" variant="outline" disabled={send.isPending} onClick={() => run("FAN_ON")}>
            {t("commands.fanOn")}
          </Button>
          <Button size="sm" variant="outline" disabled={send.isPending} onClick={() => run("FAN_OFF")}>
            {t("commands.fanOff")}
          </Button>
          <Button size="sm" variant="outline" disabled={send.isPending} onClick={() => run("ACK_ALERT")}>
            {t("commands.silence")}
          </Button>
        </div>
        {send.isSuccess && <p className="text-xs text-muted-foreground" role="status">{send.data && (send.data as { status?: string }).status === "FAILED" ? t("commands.failed") : t("commands.sent")}</p>}
        {send.isError && <p className="text-xs text-destructive" role="alert">{send.error.message}</p>}
      </CardContent>
    </Card>
  );
}
