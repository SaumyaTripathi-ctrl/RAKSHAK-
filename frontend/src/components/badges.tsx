import { CheckCircle2, CloudOff, ShieldAlert, ShieldCheck, ShieldQuestion, Wifi } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Badge } from "@/components/ui/badge";
import { formatDateTime } from "@/lib/format";
import { LEVEL_STYLES } from "@/lib/risk";
import type { LevelName, Verification } from "@/lib/types";
import { cn } from "@/lib/utils";

export function LevelBadge({ level, latched, className }: { level: LevelName; latched?: boolean; className?: string }) {
  const { t } = useTranslation();
  const s = LEVEL_STYLES[level];
  return (
    <span
      className={cn("inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-bold", s.bg, s.text, s.border, className)}
      data-level={level}
    >
      <span className={cn("size-2 rounded-full", s.dot, level === "CRITICAL" && latched && "animate-pulse")} aria-hidden />
      {t(`levels.${level}`)}
      {latched && <span className="font-normal opacity-80">· {t("alerts.latched")}</span>}
    </span>
  );
}

export function SyncBadge({
  online,
  backlog,
  offlineSince,
  compact = false,
}: {
  online: boolean | null | undefined;
  backlog: number;
  offlineSince?: number | null;
  compact?: boolean;
}) {
  const { t } = useTranslation();
  if (online === null || online === undefined) return <Badge variant="muted">{t("sync.unknown")}</Badge>;
  if (!online) {
    return (
      <Badge variant="warn" data-sync="offline">
        <CloudOff className="size-3.5" aria-hidden />
        {t("sync.offline")}
        {!compact && offlineSince ? <span className="font-normal"> · {t("sync.since", { time: formatDateTime(offlineSince) })}</span> : null}
      </Badge>
    );
  }
  if (backlog > 0) {
    return (
      <Badge variant="sim" data-sync="syncing">
        <Wifi className="size-3.5" aria-hidden />
        {t("sync.syncing", { count: backlog })}
      </Badge>
    );
  }
  return (
    <Badge variant="safe" data-sync="online">
      <Wifi className="size-3.5" aria-hidden />
      {t("sync.online")}
    </Badge>
  );
}

const TRUST: Record<Verification["status"], { variant: "safe" | "warn" | "crit" | "muted"; icon: typeof ShieldCheck; key: string }> = {
  VERIFIED: { variant: "safe", icon: ShieldCheck, key: "verify.status.VERIFIED" },
  PARTIAL: { variant: "safe", icon: CheckCircle2, key: "verify.status.PARTIAL" },
  PENDING: { variant: "muted", icon: ShieldQuestion, key: "verify.status.PENDING" },
  TAMPERED: { variant: "crit", icon: ShieldAlert, key: "verify.status.TAMPERED" },
  LEDGER_UNREACHABLE: { variant: "warn", icon: ShieldQuestion, key: "verify.status.LEDGER_UNREACHABLE" },
};

export function TrustBadge({ status, className }: { status: Verification["status"] | null | undefined; className?: string }) {
  const { t } = useTranslation();
  const cfg = TRUST[status ?? "PENDING"] ?? TRUST.PENDING;
  const Icon = cfg.icon;
  return (
    <Badge variant={cfg.variant} className={cn("px-3 py-1 text-sm", className)} data-trust={status ?? "PENDING"}>
      <Icon className="size-4" aria-hidden />
      {t(cfg.key)}
    </Badge>
  );
}
