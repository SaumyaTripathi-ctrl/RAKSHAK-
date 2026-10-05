// Shapes of the Rakshak API (see backend/rakshak/api). Everything from the simulator is marked simulated.

export type Role = "admin" | "fpo" | "driver" | "exporter";
export type LevelName = "SAFE" | "WARNING" | "CRITICAL";
export type Stage = "FARM" | "FPO" | "PACKHOUSE" | "COLD_STORAGE" | "TRANSPORT" | "RETAIL";
export const STAGES: Stage[] = ["FARM", "FPO", "PACKHOUSE", "COLD_STORAGE", "TRANSPORT", "RETAIL"];

export interface User {
  username: string;
  role: Role;
  full_name: string;
  organisation: string;
  language: string;
}

export interface Shipment {
  id: string;
  food_type: string;
  variety: string;
  weight_kg: number;
  grade: string;
  origin_name: string;
  origin_lat: number | null;
  origin_lon: number | null;
  dest_name: string;
  dest_lat: number | null;
  dest_lon: number | null;
  status: "CREATED" | "IN_TRANSIT" | "DELIVERED";
  hub_id: string | null;
  created_by: string;
  created_at: string;
  closed_at: string | null;
  model_profile: "real" | "demo";
}

export interface Driver {
  factor: string;
  severity: number;
  text: string;
}

export interface RerouteSummary {
  facility: string;
  facility_id: string;
  distance_km: number;
  duration_min: number;
  accepted: boolean;
}

export interface RiskInfo {
  shipment_id: string;
  risk: number;
  level: LevelName;
  level_code: number;
  rsl_hours: number;
  t: number;
  model_profile: "real" | "demo";
  model_note: string;
  latched: boolean;
  drivers: Driver[];
  temperature: number;
  ethylene_index: number;
  reroute: RerouteSummary | null;
}

export interface DeviceBase {
  device_id: string;
  kind: "hub" | "tag";
  name: string;
  hub_id: string | null;
  battery_pct: number | null;
  firmware_version: string;
  last_seen_at: string | null;
  online: boolean;
  backlog: number;
  offline_since: number | null;
  time_utc: number | null;
}

export interface LiveHub extends DeviceBase {
  temp_c: number | null;
  rh_pct: number | null;
  shock_g: number | null;
  lat: number | null;
  lon: number | null;
  flap_pct: number | null;
  fan_on: boolean | null;
  alert_level: number | null;
}

export interface LiveTag extends DeviceBase {
  temp_c: number | null;
  rh_pct: number | null;
  ethylene_idx: number | null;
  lid_open: boolean | null;
}

export interface Live {
  shipment_id: string;
  hub: LiveHub | null;
  tags: LiveTag[];
  aggregates: {
    temp_c: number | null;
    temp_max_c: number | null;
    rh_pct: number | null;
    ethylene_idx: number | null;
    lid_open: boolean;
  };
  sync: { online: boolean | null; backlog: number; offline_since: number | null };
  risk: RiskInfo | null;
}

export interface HubPoint {
  t: number;
  temp_c: number | null;
  rh_pct: number | null;
  shock_g: number | null;
  flap_pct: number | null;
  fan_on: boolean | null;
  batt_pct: number | null;
  alert_level: number | null;
  estimated: boolean;
}
export interface TagPoint {
  t: number;
  temp_c: number | null;
  rh_pct: number | null;
  ethylene_idx: number | null;
  lid_open: boolean | null;
  estimated: boolean;
}
export interface OfflineSegment {
  start: number;
  end: number | null;
  backlog_at_end: number | null;
}
export interface Timeline {
  shipment_id: string;
  hub: HubPoint[];
  tags: Record<string, TagPoint[]>;
  gps: { t: number; lat: number; lon: number }[];
  offline_segments: OfflineSegment[];
  events?: ApiEvent[];
}

export type Severity = "info" | "warning" | "critical";
export interface ApiEvent {
  id: number;
  shipment_id: string | null;
  device_id: string | null;
  kind: string;
  severity: Severity;
  message: string;
  data: Record<string, unknown>;
  created_at: string;
  acknowledged_by: string | null;
  acknowledged_at: string | null;
}

export interface RiskPointDto {
  t: number;
  risk: number;
  rsl_hours: number;
  level: number;
  profile: string;
}

export interface Facility {
  id: string;
  name: string;
  type: string;
  state: string;
  town: string;
  lat: number;
  lng: number;
  storage_min: number;
  storage_max: number;
  capacity_tonnes: number;
  free_tonnes: number;
  active: boolean;
  data_source: string;
}

export interface RerouteOption {
  facility: Facility;
  straight_km: number;
  distance_km: number;
  duration_min: number;
  routing_source: string;
  routing_status: string;
  reachable_before_spoilage: boolean | null;
  note: string | null;
  geometry?: [number, number][] | null;
}
export interface RerouteDoc {
  origin: { lat: number; lon: number };
  recommended: RerouteOption | null;
  alternatives: RerouteOption[];
  reason: string;
  accepted_facility_id?: string | null;
}

export interface FleetTruck {
  shipment_id: string;
  food_type: string;
  hub_id: string | null;
  lat: number | null;
  lon: number | null;
  level: number;
  risk: RiskInfo | null;
  online: boolean | null;
  temp_c: number | null;
  backlog: number;
  origin: string;
  destination: string;
  origin_lat?: number | null;
  origin_lon?: number | null;
  dest_lat?: number | null;
  dest_lon?: number | null;
}
export interface RoadRoute {
  distance_km: number;
  duration_min: number;
  source: string;
  status: string;
  geometry: [number, number][] | null;
}
export interface FleetOverview {
  kpis: { active_shipments: number; at_risk: number; offline_hubs: number; verified_batches: number };
  trucks: FleetTruck[];
}

export interface Handover {
  id: number;
  shipment_id: string;
  stage: Stage;
  actor_username: string;
  actor_name: string;
  actor_role: Role;
  organisation: string;
  location: string;
  lat: number | null;
  lon: number | null;
  notes: string;
  created_at: string;
  prev_hash: string;
  payload_hash: string;
  public_key: string;
  signature: string;
  batch_id: number | null;
  ledger_ref: string | null;
}

export interface BatchCheck {
  batch_id: number;
  device_id: string;
  first_seq: number;
  last_seq: number;
  leaf_count: number;
  merkle_root: string;
  ledger_ref: string | null;
  status: "verified" | "tampered" | "pending" | "ledger_unreachable";
  anchored_at: string;
  problems: string[];
}
export interface HandoverCheck {
  id: number;
  stage: Stage;
  anchored: boolean;
  ledger_ref: string | null;
  ok: boolean;
  problems: string[];
  organisation: string;
  at: string;
}
export interface Verification {
  shipment_id: string;
  status: "VERIFIED" | "PARTIAL" | "PENDING" | "TAMPERED" | "LEDGER_UNREACHABLE";
  verified: boolean;
  tampered: boolean;
  anchored_records: number;
  unanchored_records: number;
  total_records: number;
  coverage: number;
  batches: BatchCheck[];
  handovers: HandoverCheck[];
  unanchored_problems: string[];
  ledger: { backend: string; decentralised: boolean; integrity_ok: boolean; entries: number; problem: string };
  checked_at: number;
}
export interface LedgerEntry {
  ref: string;
  kind: string;
  payload: Record<string, unknown>;
  ts: number;
  prev_hash: string;
  hash: string;
}

export interface DeviceRow {
  id: string;
  kind: "hub" | "tag";
  name: string;
  hub_id: string | null;
  shipment_id: string | null;
  key_epoch: number;
  firmware_version: string;
  battery_pct: number | null;
  last_seen_at: string | null;
  online: boolean;
  backlog: number;
  offline_since: number | null;
  last_seq: number | null;
  last_hash: string | null;
}

export interface FoodType {
  food_type: string;
  min_temp: number;
  max_temp: number;
  min_rh: number;
  max_rh: number;
  ethylene_sensitive: boolean;
  ethylene_producer: boolean;
  source: string;
  verification_status: string;
}

export interface PublicDoc {
  shipment_id: string;
  food_type: string;
  variety: string;
  weight_kg: number;
  grade: string;
  origin: { name: string; lat: number | null; lon: number | null };
  destination: { name: string; lat: number | null; lon: number | null };
  status: string;
  created_at: string;
  journey: { stage: Stage; organisation: string; role: string; location: string; lat: number | null; lon: number | null; at: string; anchored: boolean }[];
  route: { lat: number; lon: number }[];
  chart: { t: number; temp_c: number; rh_pct: number | null; ethylene_idx: number }[];
  offline_segments: OfflineSegment[];
  summary: {
    records: number;
    temp_min_c: number | null;
    temp_max_c: number | null;
    temp_avg_c: number | null;
    alerts: Record<string, number>;
    tamper_events: number;
  };
  ledger: {
    verified: boolean | null;
    status?: string;
    backend?: string;
    decentralised?: boolean;
    anchored_records?: number;
    total_records?: number;
    coverage?: number;
    batches?: number;
    handovers_anchored?: number;
    note?: string | null;
  };
}

export interface SimScenario {
  name: string;
  title: string;
  description: string;
  food_type: string;
  duration_min: number;
  profile: string;
  accel: number;
  steps: { at: number; action: string; params: Record<string, unknown> }[];
}
export interface SimRun {
  id: string;
  scenario: string;
  title: string;
  hub_id: string;
  tag_ids: string[];
  shipment_id: string;
  food_type: string;
  profile: string;
  accel: number;
  state: "created" | "running" | "paused" | "finished" | "stopped" | "error";
  error: string | null;
  duration_min: number;
  pending_steps: { at: number; action: string; params: Record<string, unknown> }[];
  snapshot: {
    elapsed_min: number;
    temperature: number;
    ethylene_index: number;
    flap: number;
    fan: boolean;
    connected: boolean;
    backlog: number;
    battery: number;
    led: string;
    buzzer_latched: boolean;
    lat: number;
    lon: number;
    truth_risk: number | null;
  };
  log: string[];
  simulated: true;
}

export interface WsMessage {
  type: "hello" | "ping" | "record" | "event" | "hub_status" | "risk" | "reroute";
  data?: unknown;
}
