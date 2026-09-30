import type { LevelName } from "./types";

export const WARNING_AT = 30;
export const CRITICAL_AT = 70;

export function levelFromRisk(risk: number): LevelName {
  if (risk >= CRITICAL_AT) return "CRITICAL";
  if (risk >= WARNING_AT) return "WARNING";
  return "SAFE";
}

export function levelFromCode(code: number | null | undefined): LevelName {
  return code === 2 ? "CRITICAL" : code === 1 ? "WARNING" : "SAFE";
}

/** Tailwind classes per level (contrast checked against the card background in both themes). */
export const LEVEL_STYLES: Record<LevelName, { text: string; bg: string; border: string; dot: string; hex: string }> = {
  SAFE: {
    text: "text-green-800 dark:text-green-300",
    bg: "bg-green-100 dark:bg-green-950",
    border: "border-green-600/40",
    dot: "bg-green-600",
    hex: "#2E7D32",
  },
  WARNING: {
    text: "text-orange-900 dark:text-orange-200",
    bg: "bg-orange-100 dark:bg-orange-950",
    border: "border-orange-600/50",
    dot: "bg-orange-500",
    hex: "#E87A1E",
  },
  CRITICAL: {
    text: "text-red-800 dark:text-red-200",
    bg: "bg-red-100 dark:bg-red-950",
    border: "border-red-600/50",
    dot: "bg-red-600",
    hex: "#C62828",
  },
};

export function riskHex(risk: number | null | undefined): string {
  return risk === null || risk === undefined ? "#64748b" : LEVEL_STYLES[levelFromRisk(risk)].hex;
}
