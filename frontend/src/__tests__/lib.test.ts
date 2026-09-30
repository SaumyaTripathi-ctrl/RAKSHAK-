import { QueryClient } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";

import { clipSegments, mergeSeries } from "@/components/TrendChart";
import { splitTrail } from "@/components/ShipmentMap";
import { ApiError, AUTH_EXPIRED_EVENT, api, getToken, setToken, wsUrl } from "@/lib/api";
import { fmt, formatDuration, humanFood, shortHash, timeAgo } from "@/lib/format";
import { applyMessage, insertByTime, MAX_POINTS, patchLive, patchTimeline, type RecordMsg } from "@/lib/live";
import { levelFromCode, levelFromRisk, riskHex } from "@/lib/risk";
import type { Live, RiskInfo, Timeline } from "@/lib/types";

describe("format", () => {
  it("formats durations humanly", () => {
    expect(formatDuration(0)).toBe("0 min");
    expect(formatDuration(0.4)).toBe("24 min");
    expect(formatDuration(5)).toBe("5 h");
    expect(formatDuration(5.5)).toBe("5 h 30 min");
    expect(formatDuration(37.5)).toBe("1 d 14 h");
    expect(formatDuration(48)).toBe("2 d");
    expect(formatDuration(null)).toBe("-");
  });
  it("handles missing numbers", () => {
    expect(fmt(null)).toBe("-");
    expect(fmt(12.345, 1, " °C")).toBe("12.3 °C");
    expect(fmt(Number.NaN)).toBe("-");
  });
  it("shortens hashes, foods and ages", () => {
    expect(shortHash("abcdef0123456789abcdef")).toBe("abcdef01…cdef");
    expect(shortHash(null)).toBe("-");
    expect(humanFood("leafy_vegetables")).toBe("Leafy vegetables");
    const now = Date.parse("2026-01-01T12:00:00Z");
    expect(timeAgo("2026-01-01T11:59:55Z", now)).toBe("just now");
    expect(timeAgo("2026-01-01T11:30:00Z", now)).toBe("30 min ago");
    expect(timeAgo(null, now)).toBe("never");
  });
});

describe("risk levels", () => {
  it("uses the 30 / 70 thresholds", () => {
    expect([0, 29.9, 30, 69.9, 70, 100].map(levelFromRisk)).toEqual(["SAFE", "SAFE", "WARNING", "WARNING", "CRITICAL", "CRITICAL"]);
    expect([0, 1, 2, null].map((c) => levelFromCode(c))).toEqual(["SAFE", "WARNING", "CRITICAL", "SAFE"]);
  });
  it("colours by risk", () => {
    expect(riskHex(10)).toBe("#2E7D32");
    expect(riskHex(50)).toBe("#E87A1E");
    expect(riskHex(90)).toBe("#C62828");
    expect(riskHex(null)).toBe("#64748b");
  });
});

describe("api wrapper", () => {
  it("sends the bearer token and JSON, and parses errors", async () => {
    setToken("tok");
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ ok: 1 }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    await api("/api/x", { body: { a: 1 }, query: { q: "z", skip: undefined } });
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("/api/x?q=z");
    expect((init.headers as Record<string, string>).Authorization).toBe("Bearer tok");
    expect(init.method).toBe("POST");
    vi.stubGlobal("fetch", async () => new Response(JSON.stringify({ detail: "nope" }), { status: 403 }));
    await expect(api("/api/y")).rejects.toMatchObject({ status: 403, message: "nope" });
    vi.unstubAllGlobals();
  });
  it("clears the token and notifies on 401", async () => {
    setToken("tok");
    const seen = vi.fn();
    window.addEventListener(AUTH_EXPIRED_EVENT, seen);
    vi.stubGlobal("fetch", async () => new Response("{}", { status: 401 }));
    await expect(api("/api/z")).rejects.toBeInstanceOf(ApiError);
    expect(getToken()).toBeNull();
    expect(seen).toHaveBeenCalled();
    window.removeEventListener(AUTH_EXPIRED_EVENT, seen);
    vi.unstubAllGlobals();
  });
  it("public calls never send credentials", async () => {
    setToken("tok");
    const fetchMock = vi.fn(async () => new Response("{}", { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    await api("/api/public/x", { auth: false });
    expect((fetchMock.mock.calls[0] as unknown as [string, RequestInit])[1].headers).not.toHaveProperty("Authorization");
    vi.unstubAllGlobals();
  });
  it("builds the websocket url with token and shipment", () => {
    setToken("a b");
    expect(wsUrl("RKS-1")).toMatch(/^wss?:\/\/.*\/ws\?token=a\+b&shipment_id=RKS-1$/);
  });
});

const baseTl = (): Timeline => ({ shipment_id: "S", hub: [], tags: {}, gps: [], offline_segments: [] });
const rec = (o: Partial<RecordMsg>): RecordMsg => ({
  device_id: "TAG-0001", shipment_id: "S", seq: 0, rtype: 1, time_utc: 100, time_estimated: false, temp_c: 12, rh_pct: 88,
  ethylene_idx: 10, shock_g: null, lat: null, lon: null, flap_pct: null, fan_on: null, lid_open: false, batt_pct: 90,
  alert_level: null, hash_ok: true, chain_ok: true, ...o,
});

describe("live cache patching", () => {
  it("inserts keeping time order, replacing duplicates and capping length", () => {
    let a = [{ t: 10 }, { t: 30 }];
    a = insertByTime(a, { t: 20 });
    expect(a.map((p) => p.t)).toEqual([10, 20, 30]);
    a = insertByTime(a, { t: 20, x: 1 } as { t: number });
    expect(a).toHaveLength(3);
    const big = Array.from({ length: MAX_POINTS }, (_, i) => ({ t: i }));
    expect(insertByTime(big, { t: MAX_POINTS })).toHaveLength(MAX_POINTS);
  });

  it("late (backlog) records land in the right place on the timeline", () => {
    let tl = baseTl();
    tl = patchTimeline(tl, rec({ time_utc: 300 }));
    tl = patchTimeline(tl, rec({ time_utc: 100 })); // arrives after sync, older
    tl = patchTimeline(tl, rec({ time_utc: 200, device_id: "TAG-0002" }));
    expect(tl.tags["TAG-0001"].map((p) => p.t)).toEqual([100, 300]);
    expect(Object.keys(tl.tags)).toEqual(["TAG-0001", "TAG-0002"]);
  });

  it("hub samples feed both the series and the GPS trail", () => {
    const tl = patchTimeline(baseTl(), rec({ rtype: 2, device_id: "HUB-0001", flap_pct: 50, fan_on: true, lat: 17, lon: 73 }));
    expect(tl.hub[0]).toMatchObject({ t: 100, flap_pct: 50, fan_on: true });
    expect(tl.gps).toEqual([{ t: 100, lat: 17, lon: 73 }]);
    expect(patchTimeline(baseTl(), rec({ time_utc: null }))).toEqual(baseTl()); // unknown time: ignored
  });

  const live = (): Live => ({
    shipment_id: "S",
    hub: { device_id: "HUB-0001", kind: "hub", name: "", hub_id: null, battery_pct: 90, firmware_version: "", last_seen_at: null, online: true, backlog: 0, offline_since: null, time_utc: 50, temp_c: 20, rh_pct: 70, shock_g: 0, lat: 1, lon: 2, flap_pct: 0, fan_on: false, alert_level: 0 },
    tags: [
      { device_id: "TAG-0001", kind: "tag", name: "", hub_id: "HUB-0001", battery_pct: 90, firmware_version: "", last_seen_at: null, online: true, backlog: 0, offline_since: null, time_utc: 50, temp_c: 10, rh_pct: 80, ethylene_idx: 5, lid_open: false },
      { device_id: "TAG-0002", kind: "tag", name: "", hub_id: "HUB-0001", battery_pct: 80, firmware_version: "", last_seen_at: null, online: true, backlog: 0, offline_since: null, time_utc: 50, temp_c: 14, rh_pct: 90, ethylene_idx: 9, lid_open: false },
    ],
    aggregates: { temp_c: 12, temp_max_c: 14, rh_pct: 85, ethylene_idx: 9, lid_open: false },
    sync: { online: true, backlog: 0, offline_since: null },
    risk: null,
  });

  it("recomputes crate aggregates from the newest tag reading only", () => {
    const l = patchLive(live(), rec({ device_id: "TAG-0001", time_utc: 60, temp_c: 16, ethylene_idx: 40, lid_open: true }));
    expect(l.aggregates.temp_c).toBeCloseTo(15);
    expect(l.aggregates.temp_max_c).toBe(16);
    expect(l.aggregates.ethylene_idx).toBe(40);
    expect(l.aggregates.lid_open).toBe(true);
    const stale = patchLive(live(), rec({ device_id: "TAG-0001", time_utc: 10, temp_c: 99 })); // older than what we show
    expect(stale.tags[0].temp_c).toBe(10);
  });

  it("applies risk, event, hub_status and reroute messages to the query cache", () => {
    const qc = new QueryClient();
    qc.setQueryData(["live", "S"], live());
    qc.setQueryData(["risk", "S"], { shipment_id: "S", points: [] });
    qc.setQueryData(["events", "S"], []);
    qc.setQueryData(["events", "all"], []);
    const risk: RiskInfo = { shipment_id: "S", risk: 75, level: "CRITICAL", level_code: 2, rsl_hours: 3, t: 99, model_profile: "demo", model_note: "", latched: true, drivers: [], temperature: 20, ethylene_index: 50, reroute: null };
    applyMessage(qc, { type: "risk", data: risk });
    expect((qc.getQueryData(["live", "S"]) as Live).risk?.level).toBe("CRITICAL");
    expect((qc.getQueryData(["risk", "S"]) as { points: unknown[] }).points).toHaveLength(1);

    const ev = { id: 1, shipment_id: "S", device_id: null, kind: "ALERT_CRITICAL", severity: "critical", message: "m", data: {}, created_at: "2026-01-01T00:00:00Z", acknowledged_by: null, acknowledged_at: null };
    applyMessage(qc, { type: "event", data: ev });
    applyMessage(qc, { type: "event", data: { ...ev, acknowledged_by: "driver" } }); // same id replaces
    expect((qc.getQueryData(["events", "S"]) as unknown[]).length).toBe(1);
    expect((qc.getQueryData(["events", "all"]) as { acknowledged_by: string }[])[0].acknowledged_by).toBe("driver");

    applyMessage(qc, { type: "hub_status", data: { device_id: "HUB-0001", online: false, backlog: 12, offline_since: 70, battery_pct: 88, firmware_version: "", last_seen_at: null } });
    const l = qc.getQueryData(["live", "S"]) as Live;
    expect(l.sync).toEqual({ online: false, backlog: 12, offline_since: 70 });
    expect(l.hub?.battery_pct).toBe(88);

    applyMessage(qc, { type: "reroute", data: { shipment_id: "S", recommended: null, alternatives: [], reason: "x", origin: { lat: 1, lon: 2 } } });
    expect(qc.getQueryData(["reroute", "S"])).toBeTruthy();
    applyMessage(qc, { type: "ping" }); // unknown / housekeeping messages are harmless
  });
});

describe("chart helpers", () => {
  it("merges series on one time axis", () => {
    const rows = mergeSeries([
      { key: "a", label: "a", color: "#000", points: [{ t: 2, v: 1 }, { t: 1, v: 5 }] },
      { key: "b", label: "b", color: "#000", points: [{ t: 2, v: 9 }, { t: 3, v: null }] },
    ]);
    expect(rows).toEqual([{ t: 1, a: 5 }, { t: 2, a: 1, b: 9 }, { t: 3, b: null }]);
  });
  it("clips offline segments; an open segment runs to the latest point", () => {
    expect(clipSegments([{ start: 0, end: 50, backlog_at_end: null }, { start: 80, end: null, backlog_at_end: null }, { start: 500, end: 600, backlog_at_end: null }], 10, 100)).toEqual([
      { x1: 10, x2: 50, open: false },
      { x1: 80, x2: 100, open: true },
    ]);
  });
  it("splits the GPS trail into online and offline stretches that join up", () => {
    const gps = [0, 1, 2, 3, 4, 5].map((t) => ({ t, lat: t, lon: t }));
    const parts = splitTrail(gps, [{ start: 2, end: 3, backlog_at_end: null }]);
    expect(parts.map((p) => p.offline)).toEqual([false, true, false]);
    expect(parts[1].pts[0]).toEqual(parts[0].pts.at(-1)); // no visual gap between segments
  });
});
