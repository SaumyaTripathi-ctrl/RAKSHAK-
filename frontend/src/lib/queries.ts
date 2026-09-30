// react-query hooks: one place for every endpoint the UI uses.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { del, get, post, publicGet, put } from "./api";
import type {
  ApiEvent,
  DeviceRow,
  FleetOverview,
  FoodType,
  Handover,
  LedgerEntry,
  Live,
  PublicDoc,
  RerouteDoc,
  RiskPointDto,
  Shipment,
  SimRun,
  SimScenario,
  Stage,
  Timeline,
  Verification,
} from "./types";

export const useFleet = () =>
  useQuery({ queryKey: ["fleet"], queryFn: () => get<FleetOverview>("/api/fleet/overview"), refetchInterval: 20_000 });

export const useShipments = () =>
  useQuery({ queryKey: ["shipments"], queryFn: () => get<Shipment[]>("/api/shipments"), refetchInterval: 30_000 });

export const useShipment = (id: string) =>
  useQuery({ queryKey: ["shipment", id], queryFn: () => get<Shipment>(`/api/shipments/${id}`) });

export const useLive = (id: string) =>
  useQuery({ queryKey: ["live", id], queryFn: () => get<Live>(`/api/shipments/${id}/live`), refetchInterval: 30_000 });

export const useTimeline = (id: string) =>
  useQuery({ queryKey: ["timeline", id], queryFn: () => get<Timeline>(`/api/shipments/${id}/timeline`), refetchInterval: 60_000 });

export const useRiskHistory = (id: string) =>
  useQuery({
    queryKey: ["risk", id],
    queryFn: () => get<{ shipment_id: string; points: RiskPointDto[] }>(`/api/shipments/${id}/risk`),
    refetchInterval: 60_000,
  });

export const useEvents = (shipmentId?: string, unackedOnly = false) =>
  useQuery({
    queryKey: ["events", shipmentId ?? "all"],
    queryFn: () => get<ApiEvent[]>("/api/events", { shipment_id: shipmentId, unacked: unackedOnly || undefined, limit: 150 }),
    refetchInterval: 45_000,
  });

export const useCustody = (id: string) =>
  useQuery({ queryKey: ["custody", id], queryFn: () => get<Handover[]>(`/api/shipments/${id}/custody`) });

export const useVerify = (id: string, enabled = true) =>
  useQuery({
    queryKey: ["verify", id],
    queryFn: () => get<Verification>(`/api/verify/${id}`),
    enabled,
    refetchInterval: 30_000,
  });

export const useLedgerEntries = (shipmentId?: string) =>
  useQuery({
    queryKey: ["ledger-entries", shipmentId ?? "all"],
    queryFn: () => get<LedgerEntry[]>("/api/ledger/entries", { shipment_id: shipmentId, limit: 30 }),
    refetchInterval: 60_000,
  });

export const useLedgerStatus = () =>
  useQuery({
    queryKey: ["ledger-status"],
    queryFn: () => get<{ backend: string; decentralised: boolean; integrity_ok: boolean; entries: number; problem: string }>("/api/ledger/status"),
    refetchInterval: 60_000,
  });

export const useDevices = () =>
  useQuery({ queryKey: ["devices"], queryFn: () => get<DeviceRow[]>("/api/devices"), refetchInterval: 20_000 });

export const useFoodTypes = () =>
  useQuery({ queryKey: ["food-types"], queryFn: () => get<FoodType[]>("/api/food-types"), staleTime: Infinity });

export const useReroute = (id: string, enabled: boolean) =>
  useQuery({
    queryKey: ["reroute", id],
    queryFn: () => get<RerouteDoc>(`/api/shipments/${id}/reroute`),
    enabled,
    retry: false,
  });

export const usePublicDoc = (id: string) =>
  useQuery({ queryKey: ["public", id], queryFn: () => publicGet<PublicDoc>(`/api/public/shipments/${id}`), retry: false, refetchInterval: 30_000 });

export const useSimScenarios = () =>
  useQuery({
    queryKey: ["sim-scenarios"],
    queryFn: () => get<{ scenarios: SimScenario[]; injections: string[] }>("/api/simulator/scenarios"),
    retry: false,
    staleTime: Infinity,
  });

export const useSimState = () =>
  useQuery({
    queryKey: ["sim-state"],
    queryFn: () => get<{ runs: SimRun[] }>("/api/simulator/state"),
    refetchInterval: 2_000,
    retry: false,
  });

// ---- mutations -----------------------------------------------------------------------------

export function useAckEvent() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => post<ApiEvent>(`/api/events/${id}/ack`),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["events"] }),
  });
}

export function useCreateShipment() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: Record<string, unknown>) => post<Shipment>("/api/shipments", body),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["shipments"] });
      void qc.invalidateQueries({ queryKey: ["fleet"] });
      void qc.invalidateQueries({ queryKey: ["devices"] });
    },
  });
}

export function useHandover(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { stage: Stage; location?: string; notes?: string }) => post<Handover>(`/api/shipments/${id}/handover`, body),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["custody", id] });
      void qc.invalidateQueries({ queryKey: ["verify", id] });
    },
  });
}

export function useAcceptReroute(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (facility_id: string) => post(`/api/shipments/${id}/reroute/accept`, { facility_id }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["reroute", id] }),
  });
}

export function useRefreshReroute(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => get<RerouteDoc>(`/api/shipments/${id}/reroute`, { refresh: true }),
    onSuccess: (doc) => qc.setQueryData(["reroute", id], doc),
  });
}

export function useSendCommand() {
  return useMutation({
    mutationFn: (v: { hub: string; cmd: string; arg?: number | null; shipment_id?: string }) =>
      post(`/api/devices/${v.hub}/cmd`, { cmd: v.cmd, arg: v.arg ?? null, shipment_id: v.shipment_id }),
  });
}

export function useAnchorNow(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => post(`/api/shipments/${id}/anchor`),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["verify", id] }),
  });
}

export function useBind(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { hub_id?: string | null; tag_ids: string[] }) => post<Shipment>(`/api/shipments/${id}/bind`, body),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["devices"] });
      void qc.invalidateQueries({ queryKey: ["live", id] });
    },
  });
}

export function useCreateDevice() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { id: string; kind: "hub" | "tag"; name?: string; hub_id?: string | null }) =>
      post<{ device: DeviceRow; key_epoch: number; device_key_hex: string }>("/api/devices", body),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["devices"] }),
  });
}

export function useRotateKey() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => post<{ device: DeviceRow; key_epoch: number; device_key_hex: string }>(`/api/devices/${id}/rotate-key`),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["devices"] }),
  });
}

export function useSimStart() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: Record<string, unknown>) => post<SimRun>("/api/simulator/runs", body),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["sim-state"] }),
  });
}

export function useSimInject() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { run: string; action: string; params?: Record<string, unknown> }) =>
      post<SimRun>(`/api/simulator/runs/${v.run}/inject`, { action: v.action, params: v.params ?? {} }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["sim-state"] }),
  });
}

export function useSimControl() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { run: string; op: "pause" | "resume" | "stop" }) =>
      v.op === "stop" ? del<SimRun>(`/api/simulator/runs/${v.run}`) : post<SimRun>(`/api/simulator/runs/${v.run}/${v.op}`),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["sim-state"] }),
  });
}

export function useDemoTamper() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { shipment_id: string; kind: string }) => post<{ tampered: Record<string, unknown>; next: string }>("/api/demo/tamper", v),
    onSuccess: (_d, v) => void qc.invalidateQueries({ queryKey: ["verify", v.shipment_id] }),
  });
}

export function useDemoRestore() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (shipment_id: string) => post<{ restored: number }>("/api/demo/restore", { shipment_id }),
    onSuccess: (_d, id) => void qc.invalidateQueries({ queryKey: ["verify", id] }),
  });
}

export function useSetProfile(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (model_profile: "real" | "demo") => put(`/api/shipments/${id}/model-profile`, { model_profile }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["shipment", id] });
      void qc.invalidateQueries({ queryKey: ["live", id] });
    },
  });
}
