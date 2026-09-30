import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { LevelBadge } from "@/components/badges";
import { CreateShipmentDialog } from "@/components/ShipmentForm";
import { EmptyState, ErrorState, LoadingBlock, SimulatedBadge } from "@/components/States";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { TBody, TD, TH, THead, TR, Table } from "@/components/ui/misc";
import { formatDateTime, humanFood } from "@/lib/format";
import { useFleet, useShipments } from "@/lib/queries";
import { levelFromCode } from "@/lib/risk";

export default function Shipments() {
  const { t } = useTranslation();
  const list = useShipments();
  const fleet = useFleet();
  const byId = new Map((fleet.data?.trucks ?? []).map((x) => [x.shipment_id, x]));

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-2xl font-bold tracking-tight">{t("nav.shipments")}</h1>
        <CreateShipmentDialog />
      </div>
      {list.isPending ? (
        <LoadingBlock />
      ) : list.isError ? (
        <ErrorState error={list.error} onRetry={() => void list.refetch()} />
      ) : list.data.length === 0 ? (
        <EmptyState title={t("shipment.none")} hint={t("shipment.noneHint")} />
      ) : (
        <Card>
          <Table>
            <THead>
              <TR>
                <TH>ID</TH>
                <TH>{t("shipment.foodType")}</TH>
                <TH>{t("shipment.route")}</TH>
                <TH>{t("common.status")}</TH>
                <TH>{t("cards.risk")}</TH>
                <TH>{t("shipment.hub")}</TH>
                <TH>{t("shipment.created")}</TH>
              </TR>
            </THead>
            <TBody>
              {list.data.map((s) => {
                const truck = byId.get(s.id);
                return (
                  <TR key={s.id}>
                    <TD>
                      <Link to={`/shipments/${s.id}`} className="font-semibold text-secondary underline-offset-2 hover:underline">
                        {s.id}
                      </Link>
                    </TD>
                    <TD>
                      {t(`foods.${s.food_type}`, { defaultValue: humanFood(s.food_type) })}
                      {s.variety ? <span className="text-muted-foreground"> · {s.variety}</span> : null}
                    </TD>
                    <TD className="text-muted-foreground">
                      {s.origin_name || "?"} → {s.dest_name || "?"}
                    </TD>
                    <TD>
                      <Badge variant={s.status === "DELIVERED" ? "muted" : "secondary"}>{t(`status.${s.status}`)}</Badge>
                      {s.model_profile === "demo" && <span className="ml-1"><SimulatedBadge label={t("shipment.demoModel")} /></span>}
                    </TD>
                    <TD>{truck ? <LevelBadge level={truck.risk?.level ?? levelFromCode(truck.level)} latched={truck.risk?.latched} /> : "-"}</TD>
                    <TD>{s.hub_id ?? "-"}</TD>
                    <TD className="whitespace-nowrap text-muted-foreground">{formatDateTime(s.created_at)}</TD>
                  </TR>
                );
              })}
            </TBody>
          </Table>
        </Card>
      )}
    </div>
  );
}
