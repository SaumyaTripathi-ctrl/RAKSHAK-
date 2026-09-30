import { useMemo } from "react";
import {
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ReferenceArea,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { useTranslation } from "react-i18next";

import { formatClock } from "@/lib/format";
import type { OfflineSegment } from "@/lib/types";

export interface SeriesDef {
  key: string;
  label: string;
  color: string;
  points: { t: number; v: number | null }[];
  width?: number;
  dashed?: boolean;
  step?: boolean;
}

export type Row = { t: number } & Record<string, number | null>;

/** Merge several series onto one time axis (rows sorted by t; missing values are null). */
export function mergeSeries(series: SeriesDef[]): Row[] {
  const rows = new Map<number, Row>();
  for (const s of series) {
    for (const p of s.points) {
      let row = rows.get(p.t);
      if (!row) {
        row = { t: p.t };
        rows.set(p.t, row);
      }
      row[s.key] = p.v;
    }
  }
  return [...rows.values()].sort((a, b) => a.t - b.t);
}

/** Offline segments clipped to the plotted range; an open segment extends to the latest point. */
export function clipSegments(segs: OfflineSegment[], lo: number, hi: number): { x1: number; x2: number; open: boolean }[] {
  return segs
    .map((s) => ({ x1: Math.max(s.start, lo), x2: Math.min(s.end ?? hi, hi), open: s.end === null }))
    .filter((s) => s.x2 > s.x1);
}

export function TrendChart({
  series,
  offline = [],
  band,
  unit = "",
  height = 260,
  yDomain,
}: {
  series: SeriesDef[];
  offline?: OfflineSegment[];
  band?: { min: number; max: number; label: string };
  unit?: string;
  height?: number;
  yDomain?: [number | "auto" | "dataMin" | "dataMax", number | "auto" | "dataMin" | "dataMax"];
}) {
  const { t } = useTranslation();
  const rows = useMemo(() => mergeSeries(series), [series]);
  const lo = rows[0]?.t ?? 0;
  const hi = rows[rows.length - 1]?.t ?? 0;
  const segs = useMemo(() => clipSegments(offline, lo, hi), [offline, lo, hi]);

  if (rows.length === 0) {
    return (
      <div className="flex items-center justify-center text-sm text-muted-foreground" style={{ height }}>
        {t("common.noData")}
      </div>
    );
  }
  return (
    <div style={{ height }} data-testid="trend-chart" aria-label={series.map((s) => s.label).join(", ")} role="img">
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={rows} margin={{ top: 8, right: 12, bottom: 0, left: -8 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
          <XAxis
            dataKey="t"
            type="number"
            domain={["dataMin", "dataMax"]}
            tickFormatter={(v: number) => formatClock(v)}
            stroke="hsl(var(--muted-foreground))"
            fontSize={11}
            minTickGap={36}
          />
          <YAxis stroke="hsl(var(--muted-foreground))" fontSize={11} domain={yDomain ?? ["auto", "auto"]} unit={unit} width={48} />
          <Tooltip
            labelFormatter={(v) => formatClock(Number(v), true)}
            contentStyle={{ background: "hsl(var(--card))", border: "1px solid hsl(var(--border))", borderRadius: 8, fontSize: 12 }}
            formatter={(v: number) => (typeof v === "number" ? v.toFixed(1) : v)}
          />
          <Legend wrapperStyle={{ fontSize: 12 }} />
          {band && (
            <ReferenceArea y1={band.min} y2={band.max} fill="#2E7D32" fillOpacity={0.12} stroke="#2E7D32" strokeOpacity={0.3} ifOverflow="extendDomain" label={{ value: band.label, fontSize: 10, fill: "#2E7D32", position: "insideTopRight" }} />
          )}
          {segs.map((s, i) => (
            <ReferenceArea
              key={`off-${i}`}
              x1={s.x1}
              x2={s.x2}
              fill="#64748b"
              fillOpacity={s.open ? 0.3 : 0.18}
              stroke="#64748b"
              strokeOpacity={0.4}
              strokeDasharray="4 3"
              label={i === 0 ? { value: t("charts.offline"), fontSize: 10, fill: "#64748b", position: "insideTop" } : undefined}
            />
          ))}
          {series.map((s) => (
            <Line
              key={s.key}
              dataKey={s.key}
              name={s.label}
              stroke={s.color}
              strokeWidth={s.width ?? 2}
              strokeDasharray={s.dashed ? "5 4" : undefined}
              type={s.step ? "stepAfter" : "monotone"}
              dot={false}
              connectNulls
              isAnimationActive={false}
            />
          ))}
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}
