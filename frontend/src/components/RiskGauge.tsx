import { useTranslation } from "react-i18next";

import { CRITICAL_AT, LEVEL_STYLES, WARNING_AT, levelFromRisk } from "@/lib/risk";

const CX = 100;
const CY = 100;
const R = 80;

function polar(pct: number, r = R): [number, number] {
  const a = Math.PI * (1 - pct / 100); // 0% = left, 100% = right, sweeping over the top
  return [CX + r * Math.cos(a), CY - r * Math.sin(a)];
}

function arc(from: number, to: number): string {
  const [x1, y1] = polar(from);
  const [x2, y2] = polar(to);
  return `M ${x1.toFixed(2)} ${y1.toFixed(2)} A ${R} ${R} 0 0 1 ${x2.toFixed(2)} ${y2.toFixed(2)}`;
}

/** Semicircular 0-100 spoilage-risk gauge. Zones: SAFE < 30 <= WARNING < 70 <= CRITICAL. */
export function RiskGauge({ risk, className = "" }: { risk: number | null | undefined; className?: string }) {
  const { t } = useTranslation();
  const value = risk === null || risk === undefined ? null : Math.max(0, Math.min(100, risk));
  const level = value === null ? null : levelFromRisk(value);
  const [nx, ny] = polar(value ?? 0, R - 12);
  return (
    <figure className={className}>
      <svg
        viewBox="0 0 200 122"
        role="meter"
        aria-label={t("cards.risk")}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={value === null ? undefined : Math.round(value)}
        aria-valuetext={value === null ? t("common.noData") : `${Math.round(value)} ${t(`levels.${level}`)}`}
        className="w-full"
      >
        <path d={arc(0, 100)} fill="none" stroke="hsl(var(--muted))" strokeWidth="16" strokeLinecap="round" />
        <path d={arc(0, WARNING_AT - 0.6)} fill="none" stroke={LEVEL_STYLES.SAFE.hex} strokeWidth="16" />
        <path d={arc(WARNING_AT + 0.6, CRITICAL_AT - 0.6)} fill="none" stroke={LEVEL_STYLES.WARNING.hex} strokeWidth="16" />
        <path d={arc(CRITICAL_AT + 0.6, 100)} fill="none" stroke={LEVEL_STYLES.CRITICAL.hex} strokeWidth="16" />
        {value !== null && (
          <g style={{ transition: "all 600ms ease" }}>
            <line x1={CX} y1={CY} x2={nx} y2={ny} stroke="hsl(var(--foreground))" strokeWidth="3.5" strokeLinecap="round" />
            <circle cx={CX} cy={CY} r="6" fill="hsl(var(--foreground))" />
          </g>
        )}
        <text x={CX} y={CY + 18} textAnchor="middle" className="fill-foreground text-[26px] font-bold" style={{ fontVariantNumeric: "tabular-nums" }}>
          {value === null ? "-" : Math.round(value)}
        </text>
        <text x="14" y="118" className="fill-muted-foreground text-[9px]">
          0
        </text>
        <text x="186" y="118" textAnchor="end" className="fill-muted-foreground text-[9px]">
          100
        </text>
      </svg>
    </figure>
  );
}
