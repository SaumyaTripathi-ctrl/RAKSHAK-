import type { ApiEvent, FleetOverview, Handover, Live, PublicDoc, RerouteDoc, RiskInfo, Shipment, Timeline, Verification } from "@/lib/types";

export const SHIPMENT: Shipment = {
  id: "RKS-26-000001",
  food_type: "mango",
  variety: "Alphonso (Hapus)",
  weight_kg: 1200,
  grade: "A",
  origin_name: "Ratnagiri (demo)",
  origin_lat: 16.99,
  origin_lon: 73.31,
  dest_name: "Pune market yard (demo)",
  dest_lat: 18.52,
  dest_lon: 73.86,
  status: "IN_TRANSIT",
  hub_id: "HUB-0001",
  created_by: "fpo",
  created_at: "2026-09-30T10:00:00Z",
  closed_at: null,
  model_profile: "demo",
};

export const RISK: RiskInfo = {
  shipment_id: SHIPMENT.id,
  risk: 82.4,
  level: "CRITICAL",
  level_code: 2,
  rsl_hours: 3.5,
  t: 1_791_000_600,
  model_profile: "demo",
  model_note: "trained on simulated data",
  latched: true,
  drivers: [
    { factor: "temperature", severity: 3, text: "Temperature 19.1 °C is 6.1 °C above the 13 °C limit" },
    { factor: "ethylene", severity: 2, text: "Ethylene index 55%, rising 12 pts/h" },
  ],
  temperature: 19.1,
  ethylene_index: 55,
  reroute: { facility: "Fruit & vegetable cold store #5 near Chiplun (SYNTHETIC)", facility_id: "SYN-0044", distance_km: 41.2, duration_min: 82, accepted: false },
};

export const LIVE: Live = {
  shipment_id: SHIPMENT.id,
  hub: {
    device_id: "HUB-0001", kind: "hub", name: "Hub 1", hub_id: null, battery_pct: 87, firmware_version: "sim-0.1.0",
    last_seen_at: new Date().toISOString(), online: true, backlog: 0, offline_since: null, time_utc: 1_791_000_600,
    temp_c: 27.5, rh_pct: 60, shock_g: 0.35, lat: 17.1, lon: 73.4, flap_pct: 100, fan_on: true, alert_level: 1,
  },
  tags: [
    { device_id: "TAG-0001", kind: "tag", name: "", hub_id: "HUB-0001", battery_pct: 91, firmware_version: "", last_seen_at: null, online: true, backlog: 0, offline_since: null, time_utc: 1_791_000_600, temp_c: 19.1, rh_pct: 84, ethylene_idx: 55, lid_open: false },
    { device_id: "TAG-0002", kind: "tag", name: "", hub_id: "HUB-0001", battery_pct: 12, firmware_version: "", last_seen_at: null, online: true, backlog: 0, offline_since: null, time_utc: 1_791_000_600, temp_c: 19.3, rh_pct: 85, ethylene_idx: 52, lid_open: true },
  ],
  aggregates: { temp_c: 19.2, temp_max_c: 19.3, rh_pct: 84.5, ethylene_idx: 55, lid_open: true },
  sync: { online: true, backlog: 0, offline_since: null },
  risk: RISK,
};

export const TIMELINE: Timeline = {
  shipment_id: SHIPMENT.id,
  hub: [
    { t: 1_791_000_000, temp_c: 26, rh_pct: 60, shock_g: 0.1, flap_pct: 0, fan_on: false, batt_pct: 90, alert_level: 0, estimated: false },
    { t: 1_791_000_300, temp_c: 27, rh_pct: 60, shock_g: 0.2, flap_pct: 50, fan_on: true, batt_pct: 89, alert_level: 1, estimated: false },
  ],
  tags: {
    "TAG-0001": [
      { t: 1_791_000_000, temp_c: 11.5, rh_pct: 88, ethylene_idx: 5, lid_open: false, estimated: false },
      { t: 1_791_000_300, temp_c: 15, rh_pct: 86, ethylene_idx: 30, lid_open: false, estimated: false },
    ],
  },
  gps: [{ t: 1_791_000_000, lat: 17, lon: 73.3 }, { t: 1_791_000_300, lat: 17.1, lon: 73.4 }],
  offline_segments: [{ start: 1_791_000_100, end: 1_791_000_200, backlog_at_end: 30 }],
};

export const EVENTS: ApiEvent[] = [
  { id: 3, shipment_id: SHIPMENT.id, device_id: null, kind: "ALERT_CRITICAL", severity: "critical", message: "CRITICAL - RKS-26-000001: risk 82 (4 h safe life left)", data: { source: "ai" }, created_at: new Date().toISOString(), acknowledged_by: null, acknowledged_at: null },
  { id: 2, shipment_id: SHIPMENT.id, device_id: "TAG-0002", kind: "LID_OPEN", severity: "warning", message: "TAG-0002: lid opened (possible tamper)", data: {}, created_at: new Date().toISOString(), acknowledged_by: null, acknowledged_at: null },
  { id: 1, shipment_id: SHIPMENT.id, device_id: "HUB-0001", kind: "HUB_ONLINE", severity: "info", message: "HUB-0001 back online", data: {}, created_at: new Date().toISOString(), acknowledged_by: null, acknowledged_at: null },
];

export const FLEET: FleetOverview = {
  kpis: { active_shipments: 3, at_risk: 1, offline_hubs: 1, verified_batches: 7 },
  trucks: [
    { shipment_id: SHIPMENT.id, food_type: "mango", hub_id: "HUB-0001", lat: 17.1, lon: 73.4, level: 2, risk: RISK, online: true, temp_c: 19.2, backlog: 0, origin: "Ratnagiri", destination: "Pune" },
    { shipment_id: "RKS-26-000002", food_type: "banana", hub_id: "HUB-0002", lat: 20.5, lon: 74.8, level: 0, risk: null, online: false, temp_c: 13.5, backlog: 0, origin: "Jalgaon", destination: "Nashik" },
  ],
};

export const REROUTE: RerouteDoc = {
  origin: { lat: 17.1, lon: 73.4 },
  reason: "nearest of 40 compatible facilities by road time (mango band 10-13 C)",
  accepted_facility_id: null,
  recommended: {
    facility: { id: "SYN-0044", name: "Fruit & vegetable cold store #5 near Chiplun (SYNTHETIC)", type: "cold_storage", state: "Maharashtra", town: "Chiplun", lat: 17.5, lng: 73.5, storage_min: 10, storage_max: 14, capacity_tonnes: 300, free_tonnes: 40, active: true, data_source: "synthetic" },
    straight_km: 38, distance_km: 41.2, duration_min: 82, routing_source: "haversine", routing_status: "estimated", reachable_before_spoilage: true, note: null,
  },
  alternatives: [
    {
      facility: { id: "SYN-0051", name: "Multi-commodity cold store #9 near Ratnagiri (SYNTHETIC)", type: "cold_storage", state: "Maharashtra", town: "Ratnagiri", lat: 16.9, lng: 73.3, storage_min: 2, storage_max: 14, capacity_tonnes: 900, free_tonnes: 120, active: true, data_source: "synthetic" },
      straight_km: 25, distance_km: 28.5, duration_min: 95, routing_source: "osrm", routing_status: "road_route", reachable_before_spoilage: false, note: null,
    },
  ],
};

export const HANDOVERS: Handover[] = [
  { id: 1, shipment_id: SHIPMENT.id, stage: "FARM", actor_username: "fpo", actor_name: "Ramesh Patil", actor_role: "fpo", organisation: "Konkan Hapus FPO (demo)", location: "Ratnagiri farm gate", lat: null, lon: null, notes: "Loaded 1200 kg", created_at: "2026-09-30T10:05:00Z", prev_hash: "00".repeat(32), payload_hash: "ab".repeat(32), public_key: "cd".repeat(32), signature: "ef".repeat(64), batch_id: 1, ledger_ref: "local:3" },
  { id: 2, shipment_id: SHIPMENT.id, stage: "TRANSPORT", actor_username: "driver", actor_name: "Sunil Jadhav", actor_role: "driver", organisation: "Sahyadri Transport (demo)", location: "", lat: null, lon: null, notes: "", created_at: "2026-09-30T10:20:00Z", prev_hash: "ab".repeat(32), payload_hash: "12".repeat(32), public_key: "34".repeat(32), signature: "56".repeat(64), batch_id: 1, ledger_ref: "local:5" },
];

export function verification(status: Verification["status"]): Verification {
  const tampered = status === "TAMPERED";
  return {
    shipment_id: SHIPMENT.id,
    status,
    verified: status === "VERIFIED" || status === "PARTIAL",
    tampered,
    anchored_records: 100,
    unanchored_records: status === "PARTIAL" ? 5 : 0,
    total_records: status === "PARTIAL" ? 105 : 100,
    coverage: status === "PARTIAL" ? 0.95 : 1,
    batches: [
      { batch_id: 1, device_id: "TAG-0001", first_seq: 0, last_seq: 49, leaf_count: 50, merkle_root: "a1".repeat(32), ledger_ref: "local:1", status: "verified", anchored_at: "2026-09-30T10:30:00Z", problems: [] },
      {
        batch_id: 2, device_id: "TAG-0001", first_seq: 50, last_seq: 99, leaf_count: 50, merkle_root: "b2".repeat(32), ledger_ref: "local:2",
        status: tampered ? "tampered" : "verified", anchored_at: "2026-09-30T10:40:00Z",
        problems: tampered ? ["record TAG-0001#61: displayed temp_c (6.0) differs from the signed body (12.0)", "Merkle root mismatch: recomputed 1234abcd... != ledger 5678ef01..."] : [],
      },
    ],
    handovers: [{ id: 1, stage: "FARM", anchored: true, ledger_ref: "local:3", ok: true, problems: [], organisation: "Konkan Hapus FPO", at: "2026-09-30T10:05:00Z" }],
    unanchored_problems: [],
    ledger: { backend: "local", decentralised: false, integrity_ok: true, entries: 12, problem: "" },
    checked_at: 1_791_000_900,
  };
}

export function publicDoc(ledger: PublicDoc["ledger"]): PublicDoc {
  return {
    shipment_id: SHIPMENT.id,
    food_type: "mango",
    variety: "Alphonso (Hapus)",
    weight_kg: 1200,
    grade: "A",
    origin: { name: "Ratnagiri (demo)", lat: 16.99, lon: 73.31 },
    destination: { name: "Pune market yard (demo)", lat: 18.52, lon: 73.86 },
    status: "DELIVERED",
    created_at: "2026-09-30T10:00:00Z",
    journey: [
      { stage: "FARM", organisation: "Konkan Hapus FPO (demo)", role: "fpo", location: "Ratnagiri farm gate", lat: null, lon: null, at: "2026-09-30T10:05:00Z", anchored: true },
      { stage: "TRANSPORT", organisation: "Sahyadri Transport (demo)", role: "driver", location: "", lat: null, lon: null, at: "2026-09-30T10:20:00Z", anchored: true },
      { stage: "RETAIL", organisation: "Fresh Exports Ltd (demo)", role: "exporter", location: "Pune", lat: null, lon: null, at: "2026-09-30T14:20:00Z", anchored: false },
    ],
    route: [{ lat: 17, lon: 73.3 }, { lat: 17.5, lon: 73.6 }, { lat: 18.5, lon: 73.85 }],
    chart: [
      { t: 1_791_000_000, temp_c: 11.5, rh_pct: 88, ethylene_idx: 5 },
      { t: 1_791_000_600, temp_c: 12.5, rh_pct: 87, ethylene_idx: 12 },
    ],
    offline_segments: [{ start: 1_791_000_100, end: 1_791_000_200, backlog_at_end: 30 }],
    summary: { records: 120, temp_min_c: 11.2, temp_max_c: 14.8, temp_avg_c: 12.6, alerts: {}, tamper_events: 0 },
    ledger,
  };
}
