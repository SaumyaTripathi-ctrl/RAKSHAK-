import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";

export type Tone = "default" | "safe" | "warn" | "crit" | "muted";
const TONE: Record<Tone, string> = {
  default: "",
  safe: "border-l-4 border-l-green-600",
  warn: "border-l-4 border-l-orange-500",
  crit: "border-l-4 border-l-red-600",
  muted: "opacity-80",
};

export function StatCard({
  icon: Icon,
  label,
  value,
  unit,
  sub,
  tone = "default",
  children,
  className,
}: {
  icon?: LucideIcon;
  label: string;
  value?: ReactNode;
  unit?: string;
  sub?: ReactNode;
  tone?: Tone;
  children?: ReactNode;
  className?: string;
}) {
  return (
    <Card className={cn("p-4", TONE[tone], className)} data-testid={`stat-${label}`}>
      <div className="flex items-center justify-between gap-2 text-sm text-muted-foreground">
        <span className="font-medium">{label}</span>
        {Icon && <Icon className="size-4 shrink-0" aria-hidden />}
      </div>
      {value !== undefined && (
        <p className="mt-1 flex items-baseline gap-1 text-2xl font-bold tabular-nums tracking-tight sm:text-3xl">
          {value}
          {unit && <span className="text-sm font-medium text-muted-foreground">{unit}</span>}
        </p>
      )}
      {children}
      {sub && <div className="mt-1 text-xs text-muted-foreground">{sub}</div>}
    </Card>
  );
}
