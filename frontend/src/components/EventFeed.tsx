import { AlertOctagon, AlertTriangle, CheckCircle2, Info, Link2, ShieldAlert } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/lib/auth";
import { timeAgo } from "@/lib/format";
import { useAckEvent } from "@/lib/queries";
import type { ApiEvent } from "@/lib/types";
import { cn } from "@/lib/utils";

const ICON = { info: Info, warning: AlertTriangle, critical: AlertOctagon } as const;
const TONE = {
  info: "text-secondary",
  warning: "text-orange-600 dark:text-orange-400",
  critical: "text-red-600 dark:text-red-400",
} as const;

function iconFor(e: ApiEvent) {
  if (e.kind.startsWith("TAMPER") || e.kind === "AUTH_FAILED") return ShieldAlert;
  if (e.kind === "LEDGER_ANCHORED") return Link2;
  if (e.kind === "RECOVERED") return CheckCircle2;
  return ICON[e.severity];
}

export function EventFeed({ events, showShipment = true, limit = 30 }: { events: ApiEvent[]; showShipment?: boolean; limit?: number }) {
  const { t } = useTranslation();
  const { can } = useAuth();
  const ack = useAckEvent();
  return (
    <ul className="divide-y" aria-live="polite">
      {events.slice(0, limit).map((e) => {
        const Icon = iconFor(e);
        const canAck = e.severity !== "info" && !e.acknowledged_at && can("admin", "fpo", "driver");
        return (
          <li key={e.id} className="flex gap-3 py-2.5" data-severity={e.severity}>
            <Icon className={cn("mt-0.5 size-4 shrink-0", e.kind.startsWith("TAMPER") ? "text-red-600" : TONE[e.severity])} aria-hidden />
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-muted-foreground">
                <Badge variant={e.severity === "critical" ? "crit" : e.severity === "warning" ? "warn" : "muted"}>
                  {t(`events.kind.${e.kind}`, { defaultValue: e.kind })}
                </Badge>
                <time dateTime={e.created_at}>{timeAgo(e.created_at)}</time>
                {showShipment && e.shipment_id && (
                  <Link className="font-medium text-secondary underline-offset-2 hover:underline" to={`/shipments/${e.shipment_id}`}>
                    {e.shipment_id}
                  </Link>
                )}
                {e.data?.source === "ai" && <Badge variant="sim">AI</Badge>}
                {e.data?.historical === true && <Badge variant="muted">{t("events.historical")}</Badge>}
              </div>
              <p className="mt-0.5 text-sm">{e.message}</p>
              {e.acknowledged_at && (
                <p className="text-xs text-muted-foreground">{t("alerts.acknowledgedBy", { name: e.acknowledged_by })}</p>
              )}
            </div>
            {canAck && (
              <Button size="sm" variant="outline" disabled={ack.isPending} onClick={() => ack.mutate(e.id)}>
                {t("common.acknowledge")}
              </Button>
            )}
          </li>
        );
      })}
    </ul>
  );
}
