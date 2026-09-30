// Formatting helpers. Device times are epoch seconds (possibly *simulated* time), shown in the browser's zone.

export function fmt(v: number | null | undefined, digits = 1, unit = ""): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "-";
  return `${v.toFixed(digits)}${unit}`;
}

/** 37.5 h -> "1 d 13 h"; 0.4 h -> "24 min"; >= 240 h -> "10+ d". */
export function formatDuration(hours: number | null | undefined): string {
  if (hours === null || hours === undefined || Number.isNaN(hours)) return "-";
  if (hours <= 0) return "0 min";
  if (hours < 1) return `${Math.max(1, Math.round(hours * 60))} min`;
  if (hours < 24) {
    const h = Math.floor(hours);
    const m = Math.round((hours - h) * 60);
    return m ? `${h} h ${m} min` : `${h} h`;
  }
  const d = Math.floor(hours / 24);
  const h = Math.round(hours - d * 24);
  return h ? `${d} d ${h} h` : `${d} d`;
}

export function formatMinutes(min: number | null | undefined): string {
  if (min === null || min === undefined) return "-";
  return formatDuration(min / 60);
}

export function formatClock(epoch: number | null | undefined, withSeconds = false): string {
  if (epoch === null || epoch === undefined) return "-";
  return new Date(epoch * 1000).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    ...(withSeconds ? { second: "2-digit" } : {}),
  });
}

export function formatDateTime(epochOrIso: number | string | null | undefined): string {
  if (epochOrIso === null || epochOrIso === undefined) return "-";
  const d = typeof epochOrIso === "number" ? new Date(epochOrIso * 1000) : new Date(epochOrIso);
  if (Number.isNaN(d.getTime())) return "-";
  return d.toLocaleString([], { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
}

export function timeAgo(iso: string | null | undefined, now: number = Date.now()): string {
  if (!iso) return "never";
  const s = Math.max(0, Math.round((now - new Date(iso).getTime()) / 1000));
  if (s < 10) return "just now";
  if (s < 60) return `${s} s ago`;
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  return `${Math.floor(s / 86400)} d ago`;
}

export function shortHash(h: string | null | undefined, n = 8): string {
  return h ? `${h.slice(0, n)}…${h.slice(-4)}` : "-";
}

export function humanFood(type: string): string {
  return type.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
}
