// Live push -> react-query cache. Pure functions (easy to test) plus a small reconnecting WebSocket hook.
import { useQueryClient, type QueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { getToken, wsUrl } from "./api";
import type {
  ApiEvent,
  HubPoint,
  Live,
  RerouteDoc,
  RiskInfo,
  RiskPointDto,
  TagPoint,
  Timeline,
  WsMessage,
} from "./types";

export const MAX_POINTS = 3000;

export interface RecordMsg {
  device_id: string;
  shipment_id: string;
  seq: number;
  rtype: number;
  time_utc: number | null;
  time_estimated: boolean;
  temp_c: number | null;
  rh_pct: number | null;
  ethylene_idx: number | null;
  shock_g: number | null;
  lat: number | null;
  lon: number | null;
  flap_pct: number | null;
  fan_on: boolean | null;
  lid_open: boolean | null;
  batt_pct: number | null;
  alert_level: number | null;
  hash_ok: boolean;
  chain_ok: boolean;
}

/** Insert keeping ascending ``t``; replaces a point with the same ``t`` (a re-based or redelivered record). */
export function insertByTime<T extends { t: number }>(arr: T[], pt: T, max = MAX_POINTS): T[] {
  const out = arr.slice();
  let i = out.length;
  while (i > 0 && out[i - 1].t > pt.t) i--;
  if (i > 0 && out[i - 1].t === pt.t) out[i - 1] = pt;
  else out.splice(i, 0, pt);
  return out.length > max ? out.slice(out.length - max) : out;
}

export function patchTimeline(tl: Timeline, r: RecordMsg): Timeline {
  if (r.time_utc === null) return tl;
  const t = r.time_utc;
  if (r.rtype === 1) {
    const pt: TagPoint = {
      t,
      temp_c: r.temp_c,
      rh_pct: r.rh_pct,
      ethylene_idx: r.ethylene_idx,
      lid_open: r.lid_open,
      estimated: r.time_estimated,
    };
    return { ...tl, tags: { ...tl.tags, [r.device_id]: insertByTime(tl.tags[r.device_id] ?? [], pt) } };
  }
  if (r.rtype === 2) {
    const pt: HubPoint = {
      t,
      temp_c: r.temp_c,
      rh_pct: r.rh_pct,
      shock_g: r.shock_g,
      flap_pct: r.flap_pct,
      fan_on: r.fan_on,
      batt_pct: r.batt_pct,
      alert_level: r.alert_level,
      estimated: r.time_estimated,
    };
    const gps = r.lat !== null && r.lon !== null ? insertByTime(tl.gps, { t, lat: r.lat, lon: r.lon }) : tl.gps;
    return { ...tl, hub: insertByTime(tl.hub, pt), gps };
  }
  return tl;
}

export function patchLive(live: Live, r: RecordMsg): Live {
  if (r.rtype === 1) {
    const tags = live.tags.map((tg) =>
      tg.device_id === r.device_id && (tg.time_utc ?? 0) <= (r.time_utc ?? 0)
        ? {
            ...tg,
            time_utc: r.time_utc,
            temp_c: r.temp_c,
            rh_pct: r.rh_pct,
            ethylene_idx: r.ethylene_idx,
            lid_open: r.lid_open,
            battery_pct: r.batt_pct ?? tg.battery_pct,
          }
        : tg,
    );
    const temps = tags.map((x) => x.temp_c).filter((v): v is number => v !== null);
    const eth = tags.map((x) => x.ethylene_idx).filter((v): v is number => v !== null);
    const rhs = tags.map((x) => x.rh_pct).filter((v): v is number => v !== null);
    return {
      ...live,
      tags,
      aggregates: {
        ...live.aggregates,
        temp_c: temps.length ? temps.reduce((a, b) => a + b, 0) / temps.length : live.aggregates.temp_c,
        temp_max_c: temps.length ? Math.max(...temps) : live.aggregates.temp_max_c,
        rh_pct: rhs.length ? rhs.reduce((a, b) => a + b, 0) / rhs.length : live.aggregates.rh_pct,
        ethylene_idx: eth.length ? Math.max(...eth) : live.aggregates.ethylene_idx,
        lid_open: tags.some((x) => x.lid_open),
      },
    };
  }
  if (r.rtype === 2 && live.hub && (live.hub.time_utc ?? 0) <= (r.time_utc ?? 0)) {
    return {
      ...live,
      hub: {
        ...live.hub,
        time_utc: r.time_utc,
        temp_c: r.temp_c,
        rh_pct: r.rh_pct,
        shock_g: r.shock_g,
        flap_pct: r.flap_pct,
        fan_on: r.fan_on,
        alert_level: r.alert_level,
        battery_pct: r.batt_pct ?? live.hub.battery_pct,
        lat: r.lat ?? live.hub.lat,
        lon: r.lon ?? live.hub.lon,
      },
    };
  }
  return live;
}

export function patchRiskHistory(points: RiskPointDto[], r: RiskInfo): RiskPointDto[] {
  return insertByTime(
    points,
    { t: r.t, risk: r.risk, rsl_hours: r.rsl_hours, level: r.level_code, profile: r.model_profile },
  );
}

type HubStatus = {
  device_id: string;
  online: boolean;
  backlog: number;
  offline_since: number | null;
  battery_pct: number | null;
  firmware_version: string;
  last_seen_at: string | null;
};

let lastFleetInvalidate = 0;

export function applyMessage(qc: QueryClient, msg: WsMessage): void {
  switch (msg.type) {
    case "record": {
      const r = msg.data as RecordMsg;
      qc.setQueryData<Timeline>(["timeline", r.shipment_id], (tl) => (tl ? patchTimeline(tl, r) : tl));
      qc.setQueryData<Live>(["live", r.shipment_id], (lv) => (lv ? patchLive(lv, r) : lv));
      break;
    }
    case "risk": {
      const r = msg.data as RiskInfo;
      qc.setQueryData<Live>(["live", r.shipment_id], (lv) => (lv ? { ...lv, risk: r } : lv));
      qc.setQueryData<{ shipment_id: string; points: RiskPointDto[] }>(["risk", r.shipment_id], (h) =>
        h ? { ...h, points: patchRiskHistory(h.points, r) } : h,
      );
      break;
    }
    case "event": {
      const e = msg.data as ApiEvent;
      const add = (list?: ApiEvent[]) => {
        if (!list) return list;
        const i = list.findIndex((x) => x.id === e.id);
        if (i >= 0) {
          const copy = list.slice();
          copy[i] = e;
          return copy;
        }
        return [e, ...list].slice(0, 300);
      };
      qc.setQueryData<ApiEvent[]>(["events", e.shipment_id ?? "all"], add);
      qc.setQueryData<ApiEvent[]>(["events", "all"], add);
      if (Date.now() - lastFleetInvalidate > 3000) {
        lastFleetInvalidate = Date.now();
        void qc.invalidateQueries({ queryKey: ["fleet"] });
      }
      if (e.kind.startsWith("TAMPER") || e.kind === "LEDGER_ANCHORED" || e.kind === "HANDOVER") {
        void qc.invalidateQueries({ queryKey: ["verify", e.shipment_id] });
        void qc.invalidateQueries({ queryKey: ["custody", e.shipment_id] });
      }
      break;
    }
    case "hub_status": {
      const s = msg.data as HubStatus;
      for (const [key, lv] of qc.getQueriesData<Live>({ queryKey: ["live"] })) {
        if (!lv?.hub || lv.hub.device_id !== s.device_id) continue;
        qc.setQueryData<Live>(key, {
          ...lv,
          hub: { ...lv.hub, online: s.online, backlog: s.backlog, offline_since: s.offline_since, battery_pct: s.battery_pct, last_seen_at: s.last_seen_at },
          sync: { online: s.online, backlog: s.backlog, offline_since: s.offline_since },
        });
      }
      break;
    }
    case "reroute": {
      const d = msg.data as RerouteDoc & { shipment_id: string };
      qc.setQueryData(["reroute", d.shipment_id], d);
      break;
    }
    default:
      break;
  }
}

export type SocketState = "connecting" | "open" | "closed";

/** One reconnecting socket; ``shipmentId`` undefined = all shipments (fleet view). */
export function useLiveSocket(shipmentId?: string | null): SocketState {
  const qc = useQueryClient();
  const [state, setState] = useState<SocketState>("connecting");
  const attempts = useRef(0);

  useEffect(() => {
    if (!getToken()) return;
    let ws: WebSocket | null = null;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let closed = false;

    const connect = () => {
      setState("connecting");
      ws = new WebSocket(wsUrl(shipmentId));
      ws.onopen = () => {
        const reconnect = attempts.current > 0;
        attempts.current = 0;
        setState("open");
        if (reconnect) void qc.invalidateQueries(); // fill whatever we missed while disconnected
      };
      ws.onmessage = (ev) => {
        try {
          applyMessage(qc, JSON.parse(ev.data as string) as WsMessage);
        } catch {
          /* ignore malformed */
        }
      };
      ws.onclose = () => {
        setState("closed");
        if (closed) return;
        attempts.current += 1;
        const delay = Math.min(15000, 1000 * 2 ** Math.min(attempts.current, 4)) * (0.75 + Math.random() * 0.5);
        timer = setTimeout(connect, delay);
      };
      ws.onerror = () => ws?.close();
    };
    connect();
    return () => {
      closed = true;
      clearTimeout(timer);
      ws?.close();
    };
  }, [shipmentId, qc]);

  return state;
}
