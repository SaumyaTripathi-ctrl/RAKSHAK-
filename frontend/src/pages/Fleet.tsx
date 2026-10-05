import { Activity, AlertTriangle, CloudOff, ShieldCheck } from "lucide-react";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate } from "react-router-dom";

import { LevelBadge, SyncBadge } from "@/components/badges";
import { EventFeed } from "@/components/EventFeed";
import { CreateShipmentDialog } from "@/components/ShipmentForm";
import { ShipmentMap, type MapTruck } from "@/components/ShipmentMap";
import { EmptyState, ErrorState, LoadingBlock } from "@/components/States";
import { StatCard } from "@/components/StatCard";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { fmt, humanFood } from "@/lib/format";
import { useEvents, useFleet, useRoutes, type RoutePair } from "@/lib/queries";
import { levelFromCode } from "@/lib/risk";

export default function Fleet() {
  const { t } = useTranslation();
  const nav = useNavigate();
  const fleet = useFleet();
  const events = useEvents();

  // road routes for the most recent trucks (cached; the backend caches OSRM too)
  const pairs: RoutePair[] = useMemo(
    () =>
      (fleet.data?.trucks ?? [])
        .filter((x) => x.lat !== null && x.origin_lat != null && x.origin_lon != null && x.dest_lat != null && x.dest_lon != null)
        .slice(-12)
        .map((x) => ({ key: x.shipment_id, from: [x.origin_lat as number, x.origin_lon as number], to: [x.dest_lat as number, x.dest_lon as number] })),
    [fleet.data],
  );
  const routes = useRoutes(pairs);

  const trucks: MapTruck[] = useMemo(
    () =>
      (fleet.data?.trucks ?? [])
        .filter((x) => x.lat !== null && x.lon !== null)
        .map((x) => ({
          route: routes[x.shipment_id] ?? null,
          origin: x.origin_lat != null && x.origin_lon != null ? ([x.origin_lat, x.origin_lon] as [number, number]) : null,
          dest: x.dest_lat != null && x.dest_lon != null ? ([x.dest_lat, x.dest_lon] as [number, number]) : null,
          originName: x.origin,
          destName: x.destination,
          id: x.shipment_id,
          lat: x.lat as number,
          lon: x.lon as number,
          risk: x.risk ? x.risk.risk : x.level === 2 ? 80 : x.level === 1 ? 50 : 10,
          label: `${x.shipment_id} · ${t(`foods.${x.food_type}`, { defaultValue: humanFood(x.food_type) })}`,
          sub: `${t(`levels.${levelFromCode(x.level)}`)} · ${fmt(x.temp_c, 1, " °C")}`,
          offline: x.online === false,
          onClick: () => nav(`/shipments/${x.shipment_id}`),
        })),
    [fleet.data, nav, t, routes],
  );

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-2xl font-bold tracking-tight">{t("fleet.title")}</h1>
        <CreateShipmentDialog />
      </div>

      {fleet.isPending ? (
        <LoadingBlock rows={2} />
      ) : fleet.isError ? (
        <ErrorState error={fleet.error} onRetry={() => void fleet.refetch()} />
      ) : (
        <>
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <StatCard icon={Activity} label={t("fleet.kpi.active")} value={fleet.data.kpis.active_shipments} />
            <StatCard
              icon={AlertTriangle}
              label={t("fleet.kpi.atRisk")}
              value={fleet.data.kpis.at_risk}
              tone={fleet.data.kpis.at_risk > 0 ? "warn" : "safe"}
            />
            <StatCard
              icon={CloudOff}
              label={t("fleet.kpi.offline")}
              value={fleet.data.kpis.offline_hubs}
              tone={fleet.data.kpis.offline_hubs > 0 ? "warn" : "default"}
              sub={t("fleet.kpi.offlineHint")}
            />
            <StatCard icon={ShieldCheck} label={t("fleet.kpi.verified")} value={fleet.data.kpis.verified_batches} tone="safe" sub={t("fleet.kpi.verifiedHint")} />
          </div>

          <div className="grid gap-5 xl:grid-cols-3">
            <div className="space-y-5 xl:col-span-2">
              <Card>
                <CardHeader>
                  <CardTitle>{t("fleet.map")}</CardTitle>
                </CardHeader>
                <CardContent>
                  <ShipmentMap trucks={trucks} resetKey={`fleet-${trucks.filter((x) => x.dest).length}`} height={480} />
                  <p className="mt-2 text-xs text-muted-foreground">{t("fleet.mapLegend")}</p>
                </CardContent>
              </Card>

              <Card>
                <CardHeader>
                  <CardTitle>{t("fleet.trucks")}</CardTitle>
                </CardHeader>
                <CardContent>
                  {fleet.data.trucks.length === 0 ? (
                    <EmptyState title={t("fleet.noTrucks")} hint={t("fleet.noTrucksHint")} />
                  ) : (
                    <ul className="divide-y">
                      {fleet.data.trucks.map((x) => {
                        const level = x.risk?.level ?? levelFromCode(x.level);
                        return (
                          <li key={x.shipment_id} className="flex flex-wrap items-center gap-x-4 gap-y-1 py-3">
                            <Link to={`/shipments/${x.shipment_id}`} className="font-semibold text-secondary underline-offset-2 hover:underline">
                              {x.shipment_id}
                            </Link>
                            <span className="text-sm">{t(`foods.${x.food_type}`, { defaultValue: humanFood(x.food_type) })}</span>
                            <span className="text-sm text-muted-foreground">
                              {x.origin || "?"} → {x.destination || "?"}
                            </span>
                            <span className="ml-auto flex items-center gap-2">
                              <span className="text-sm tabular-nums">{fmt(x.temp_c, 1, " °C")}</span>
                              <SyncBadge online={x.online} backlog={x.backlog} compact />
                              <LevelBadge level={level} latched={x.risk?.latched} />
                            </span>
                          </li>
                        );
                      })}
                    </ul>
                  )}
                </CardContent>
              </Card>
            </div>

            <Card className="xl:col-span-1">
              <CardHeader>
                <CardTitle>{t("fleet.alertFeed")}</CardTitle>
              </CardHeader>
              <CardContent>
                {events.isPending ? (
                  <LoadingBlock rows={4} />
                ) : events.isError ? (
                  <ErrorState error={events.error} onRetry={() => void events.refetch()} />
                ) : events.data.length === 0 ? (
                  <EmptyState title={t("fleet.noAlerts")} />
                ) : (
                  <EventFeed events={events.data} limit={25} />
                )}
              </CardContent>
            </Card>
          </div>
        </>
      )}
    </div>
  );
}
