import { AlertTriangle, Inbox, RefreshCw } from "lucide-react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/misc";

export function LoadingBlock({ rows = 3, className = "" }: { rows?: number; className?: string }) {
  const { t } = useTranslation();
  return (
    <div role="status" aria-label={t("common.loading")} className={`space-y-3 ${className}`}>
      {Array.from({ length: rows }, (_, i) => (
        <Skeleton key={i} className="h-16 w-full" />
      ))}
      <span className="sr-only">{t("common.loading")}</span>
    </div>
  );
}

export function EmptyState({ title, hint, icon, action }: { title: string; hint?: string; icon?: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center gap-2 rounded-lg border border-dashed p-8 text-center text-muted-foreground">
      {icon ?? <Inbox className="size-8" aria-hidden />}
      <p className="font-medium text-foreground">{title}</p>
      {hint && <p className="max-w-md text-sm">{hint}</p>}
      {action}
    </div>
  );
}

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const { t } = useTranslation();
  const msg = error instanceof Error ? error.message : String(error ?? "");
  return (
    <div role="alert" className="flex flex-col items-start gap-2 rounded-lg border border-destructive/50 bg-destructive/5 p-4">
      <p className="flex items-center gap-2 font-medium text-destructive">
        <AlertTriangle className="size-4" aria-hidden /> {t("common.error")}
      </p>
      {msg && <p className="text-sm text-muted-foreground">{msg}</p>}
      {onRetry && (
        <Button size="sm" variant="outline" onClick={onRetry}>
          <RefreshCw /> {t("common.retry")}
        </Button>
      )}
    </div>
  );
}

/** Marks anything produced by the device simulator / trained on simulated data. */
export function SimulatedBadge({ label }: { label?: string }) {
  const { t } = useTranslation();
  return (
    <Badge variant="sim" title={t("app.simulatedHint")}>
      {label ?? t("app.simulated")}
    </Badge>
  );
}
