import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import i18n from "@/lib/i18n";
import { setToken } from "@/lib/api";
import { renderPage } from "@/test/utils";

import Alerts from "@/pages/Alerts";
import Custody from "@/pages/Custody";
import Devices from "@/pages/Devices";
import Fleet from "@/pages/Fleet";
import Login from "@/pages/Login";
import PublicQr from "@/pages/PublicQr";
import ShipmentDetail from "@/pages/ShipmentDetail";
import SimulatorControl from "@/pages/SimulatorControl";
import Verify from "@/pages/Verify";
import { Layout } from "@/components/Layout";
import { EventFeed } from "@/components/EventFeed";
import { RiskGauge } from "@/components/RiskGauge";
import { LevelBadge, SyncBadge, TrustBadge } from "@/components/badges";
import { EVENTS, FLEET, HANDOVERS, LIVE, REROUTE, RISK, SHIPMENT, TIMELINE, publicDoc, verification } from "./fixtures";

vi.mock("@/components/ShipmentMap", async () => {
  const React = await import("react");
  return {
    splitTrail: () => [],
    ShipmentMap: (p: { trucks: unknown[]; detour?: { facility: { id: string } } | null; alternatives?: unknown[]; trail?: unknown[] }) =>
      React.createElement("div", {
        "data-testid": "map",
        "data-trucks": p.trucks.length,
        "data-detour": p.detour?.facility.id ?? "",
        "data-alts": p.alternatives?.length ?? 0,
        "data-trail": p.trail?.length ?? 0,
      }),
  };
});

const ID = SHIPMENT.id;
const shipmentRoutes = {
  [`GET /api/shipments/${ID}`]: SHIPMENT,
  [`GET /api/shipments/${ID}/live`]: LIVE,
  [`GET /api/shipments/${ID}/timeline`]: TIMELINE,
  [`GET /api/shipments/${ID}/risk`]: { shipment_id: ID, points: [{ t: 1_791_000_000, risk: 20, rsl_hours: 8, level: 0, profile: "demo" }, { t: 1_791_000_600, risk: 82, rsl_hours: 3.5, level: 2, profile: "demo" }] },
  [`GET /api/shipments/${ID}/reroute`]: REROUTE,
  "GET /api/events": EVENTS,
  "GET /api/shipments": [SHIPMENT],
  "GET /api/fleet/overview": FLEET,
  "GET /api/food-types": [{ food_type: "mango", min_temp: 10, max_temp: 13, min_rh: 85, max_rh: 90, ethylene_sensitive: true, ethylene_producer: true, source: "USDA Agriculture Handbook 66", verification_status: "TODO-verify" }],
};

describe("Login", () => {
  it("signs in and leaves the login page", async () => {
    const { calls } = renderPage(<Login />, {
      path: "/login", role: null,
      routes: { "GET /health": { dev_secrets: false }, "POST /api/auth/login": { access_token: "tok", token_type: "bearer", user: { username: "admin", role: "admin", full_name: "Asha", organisation: "", language: "en" } } },
    });
    await userEvent.type(screen.getByLabelText("Username"), "admin");
    await userEvent.type(screen.getByLabelText("Password"), "admin123");
    await userEvent.click(screen.getByRole("button", { name: /sign in/i }));
    await screen.findByTestId("elsewhere");
    expect(calls.find((c) => c.path === "/api/auth/login")?.body).toEqual({ username: "admin", password: "admin123" });
    expect(localStorage.getItem("rakshak.token")).toBe("tok");
  });

  it("shows an error for bad credentials and never advertises demo accounts on a hardened server", async () => {
    renderPage(<Login />, { path: "/login", role: null, routes: { "GET /health": { dev_secrets: false }, "POST /api/auth/login": new Response(JSON.stringify({ detail: "incorrect username or password" }), { status: 401 }) } });
    await userEvent.type(screen.getByLabelText("Username"), "x");
    await userEvent.type(screen.getByLabelText("Password"), "y");
    await userEvent.click(screen.getByRole("button", { name: /sign in/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/incorrect/i);
    expect(screen.queryByText("Demo accounts")).not.toBeInTheDocument();
  });

  it("offers demo accounts only for a dev-secrets server, and fills the form", async () => {
    renderPage(<Login />, { path: "/login", role: null, routes: { "GET /health": { dev_secrets: true } } });
    await userEvent.click(await screen.findByRole("button", { name: "Driver" }));
    expect(screen.getByLabelText("Username")).toHaveValue("driver");
    expect(screen.getByLabelText("Password")).toHaveValue("driver123");
  });
});

describe("Public QR page", () => {
  const routes = (ledger: Parameters<typeof publicDoc>[0]) => ({ [`GET /api/public/shipments/${ID}`]: publicDoc(ledger), "GET /health": { dev_secrets: true } });

  it("shows the verified badge, journey and summary without sending credentials", async () => {
    setToken("should-not-leak");
    const { calls } = renderPage(<PublicQr />, { path: "/p/:id", route: `/p/${ID}`, role: null, routes: routes({ verified: true, status: "VERIFIED", backend: "local", coverage: 1, note: "Demo ledger: single party" }) });
    const hero = await screen.findByTestId("trust-hero");
    expect(hero).toHaveAttribute("data-verified", "true");
    expect(hero).toHaveTextContent("Verified journey");
    expect(screen.getByText("Mango")).toBeInTheDocument();
    expect(screen.getByText("Konkan Hapus FPO (demo)")).toBeInTheDocument();
    expect(screen.getByText("12.6 °C")).toBeInTheDocument();
    expect(screen.getByText("No alerts")).toBeInTheDocument();
    expect(screen.getByText(/Demo deployment/)).toBeInTheDocument();
    expect(calls.filter((c) => c.path.startsWith("/api/public")).every((c) => c.auth === null)).toBe(true);
  });

  it("is loud when tampering was detected, and never claims verification", async () => {
    renderPage(<PublicQr />, { path: "/p/:id", route: `/p/${ID}`, role: null, routes: routes({ verified: false, status: "TAMPERED" }) });
    const hero = await screen.findByTestId("trust-hero");
    expect(hero).toHaveAttribute("data-verified", "false");
    expect(hero).toHaveAttribute("data-status", "TAMPERED");
    expect(hero).toHaveTextContent("Tampering detected");
    expect(hero).not.toHaveTextContent("Verified journey");
  });

  it("does not show verified while nothing is anchored", async () => {
    renderPage(<PublicQr />, { path: "/p/:id", route: `/p/${ID}`, role: null, routes: routes({ verified: false, status: "PENDING" }) });
    expect(await screen.findByText("Not verified yet")).toBeInTheDocument();
  });

  it("switches to Hindi", async () => {
    renderPage(<PublicQr />, { path: "/p/:id", route: `/p/${ID}`, role: null, routes: routes({ verified: true, status: "VERIFIED", coverage: 1 }) });
    await screen.findByTestId("trust-hero");
    fireEvent.change(screen.getByLabelText("Language"), { target: { value: "hi" } });
    await waitFor(() => expect(screen.getByTestId("trust-hero")).toHaveTextContent("सत्यापित यात्रा"));
    expect(screen.getByText("आम")).toBeInTheDocument();
    await i18n.changeLanguage("en");
  });

  it("explains an unknown shipment", async () => {
    renderPage(<PublicQr />, { path: "/p/:id", route: "/p/NOPE", role: null, routes: { "GET /api/public/shipments/NOPE": new Response(JSON.stringify({ detail: "unknown shipment" }), { status: 404 }) } });
    expect(await screen.findByRole("alert")).toHaveTextContent("No shipment found for NOPE");
  });
});

describe("Fleet overview", () => {
  it("shows KPIs, trucks and the alert feed", async () => {
    renderPage(<Fleet />, { routes: shipmentRoutes });
    expect(await screen.findByText("Active shipments")).toBeInTheDocument();
    const kpi = (label: string) => screen.getByTestId(`stat-${label}`);
    await waitFor(() => expect(kpi("Active shipments")).toHaveTextContent("3"));
    expect(kpi("At risk")).toHaveTextContent("1");
    expect(kpi("Offline hubs")).toHaveTextContent("1");
    expect(kpi("Verified batches")).toHaveTextContent("7");
    expect(screen.getAllByText("RKS-26-000001").length).toBeGreaterThan(0);
    expect(screen.getByText("CRITICAL")).toBeInTheDocument();
    expect((await screen.findAllByText(/lid opened/i)).length).toBeGreaterThan(0);
    expect(screen.getByTestId("map")).toHaveAttribute("data-trucks", "2");
  });
});

describe("Shipment detail", () => {
  const go = (role: "admin" | "exporter" | "driver" = "admin", live = LIVE) =>
    renderPage(<ShipmentDetail />, { path: "/shipments/:id", route: `/shipments/${ID}`, role, routes: { ...shipmentRoutes, [`GET /api/shipments/${ID}/live`]: live } });

  it("renders every live card, the risk gauge and the safe-life countdown", async () => {
    go();
    await screen.findByTestId("stat-Temperature");
    expect(screen.getByTestId("stat-Temperature")).toHaveTextContent("19.2");
    expect(screen.getByTestId("stat-Humidity")).toHaveTextContent("85");
    expect(screen.getByTestId("stat-Ethylene index")).toHaveTextContent("55");
    expect(screen.getByTestId("stat-Shock")).toHaveTextContent("0.35");
    expect(screen.getByTestId("stat-PCM cooling flap")).toHaveTextContent("100");
    expect(screen.getByTestId("stat-Scrubber fan")).toHaveTextContent("ON");
    expect(screen.getByTestId("stat-Battery")).toHaveTextContent("12"); // the weakest device, flagged
    expect(screen.getByTestId("stat-Sync status")).toHaveTextContent("Online");
    expect(screen.getByTestId("safe-life")).toHaveTextContent("3 h 30 min");
    expect(screen.getByRole("meter", { name: "Spoilage risk" })).toHaveAttribute("aria-valuenow", "82");
    expect(screen.getByText(/6.1 °C above the 13 °C limit/)).toBeInTheDocument();
    expect(screen.getAllByText("Model trained on simulated data").length).toBeGreaterThan(0);
  });

  it("shows the per-crate tag table, reroute banner, map and events", async () => {
    go();
    const tags = await screen.findByText("Crate tags", { selector: "h3" });
    const card = tags.closest("div.rounded-lg") as HTMLElement;
    expect(within(card).getByText("TAG-0002")).toBeInTheDocument();
    expect(within(card).getByText("OPENED")).toBeInTheDocument();
    expect(screen.getByText(/Detour recommended: Fruit & vegetable cold store/)).toBeInTheDocument();
    await waitFor(() => expect(screen.getByTestId("map")).toHaveAttribute("data-detour", "SYN-0044"));
    expect(screen.getByTestId("map")).toHaveAttribute("data-trail", "2");
    expect(await screen.findByText(/CRITICAL - RKS-26-000001/)).toBeInTheDocument();
  });

  it("flags an offline hub with its backlog", async () => {
    go("admin", { ...LIVE, sync: { online: false, backlog: 42, offline_since: 1_791_000_100 }, hub: { ...LIVE.hub!, online: false, backlog: 42 } });
    const card = await screen.findByTestId("stat-Sync status");
    await waitFor(() => expect(card).toHaveTextContent("Offline"));
    expect(card).toHaveTextContent("backlog 42");
  });

  it("lets responders command the hub but not exporters", async () => {
    const { calls } = go("admin");
    await userEvent.click(await screen.findByRole("button", { name: "Flap ≥ 50 %" }));
    await waitFor(() => expect(calls.some((c) => c.path === "/api/devices/HUB-0001/cmd")).toBe(true));
    expect(calls.find((c) => c.path === "/api/devices/HUB-0001/cmd")?.body).toMatchObject({ cmd: "FLAP_SET", arg: 50 });
  });

  it("hides the command panel from exporters", async () => {
    go("exporter");
    await screen.findByTestId("stat-Temperature");
    expect(screen.queryByText("Hub commands")).not.toBeInTheDocument();
  });

  it("shows a helpful error when the shipment does not exist", async () => {
    renderPage(<ShipmentDetail />, { path: "/shipments/:id", route: "/shipments/NOPE", routes: { "GET /api/shipments/NOPE": new Response(JSON.stringify({ detail: "unknown shipment" }), { status: 404 }), "GET /api/shipments/NOPE/live": new Response("{}", { status: 404 }) } });
    expect(await screen.findByRole("alert")).toHaveTextContent("unknown shipment");
  });
});

describe("Alerts & rerouting", () => {
  const go = (role: "admin" | "exporter" = "admin") => renderPage(<Alerts />, { path: "/alerts/:id", route: `/alerts/${ID}`, role, routes: shipmentRoutes });

  it("presents the emergency with the recommended cold store, alternatives and honest labels", async () => {
    go();
    const region = await screen.findByRole("region", { name: "Emergency" });
    expect(region).toHaveTextContent("Spoilage risk 82 / 100");
    expect(region).toHaveTextContent("CRITICAL");
    const rec = (await screen.findAllByRole("listitem")).find((li) => li.getAttribute("data-recommended") === "true")!;
    expect(rec).toHaveTextContent("Fruit & vegetable cold store #5 near Chiplun (SYNTHETIC)");
    expect(rec).toHaveTextContent("straight-line estimate"); // no road routing: said plainly
    expect(rec).toHaveTextContent("reachable before spoilage");
    expect(rec).toHaveTextContent("82 min".replace("82 min", "1 h 22 min"));
    const alt = (await screen.findAllByRole("listitem")).find((li) => li.getAttribute("data-recommended") === "false" && li.textContent?.includes("Ratnagiri"))!;
    expect(alt).toHaveTextContent("may not arrive in time");
    expect(alt).toHaveTextContent("road route");
    expect(screen.getByTestId("map")).toHaveAttribute("data-alts", "1");
  });

  it("accepts a detour and acknowledges the latched alarm", async () => {
    const { calls } = go();
    await userEvent.click((await screen.findAllByRole("button", { name: "Accept detour" }))[0]);
    await waitFor(() => expect(calls.some((c) => c.path === `/api/shipments/${ID}/reroute/accept`)).toBe(true));
    expect(calls.find((c) => c.path.endsWith("/reroute/accept"))?.body).toEqual({ facility_id: "SYN-0044" });
    await userEvent.click(screen.getByRole("button", { name: "Acknowledge & silence" }));
    await waitFor(() => expect(calls.some((c) => c.path === "/api/events/3/ack")).toBe(true));
  });

  it("does not offer acceptance to exporters", async () => {
    go("exporter");
    await screen.findByRole("region", { name: "Emergency" });
    await screen.findAllByRole("listitem");
    expect(screen.queryByRole("button", { name: "Accept detour" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Acknowledge & silence" })).not.toBeInTheDocument();
  });
});

describe("Custody", () => {
  const routes = { ...shipmentRoutes, [`GET /api/shipments/${ID}/custody`]: HANDOVERS, [`GET /api/verify/${ID}`]: verification("VERIFIED") };

  it("shows the signed, anchored journey in order", async () => {
    renderPage(<Custody />, { path: "/custody/:id", route: `/custody/${ID}`, routes });
    const list = await screen.findByTestId("handover-list");
    const items = within(list).getAllByRole("listitem");
    expect(items).toHaveLength(2);
    expect(items[0]).toHaveTextContent("Farm");
    expect(items[0]).toHaveTextContent("Konkan Hapus FPO (demo)");
    expect(items[0]).toHaveTextContent("anchored");
    expect(items[1]).toHaveTextContent("Transport");
    expect(screen.getByLabelText("Custody stages")).toBeInTheDocument();
  });

  it("only offers the stages a role may sign, and posts the hand-over", async () => {
    const { calls } = renderPage(<Custody />, { path: "/custody/:id", route: `/custody/${ID}`, role: "fpo", routes: { ...routes, [`POST /api/shipments/${ID}/handover`]: HANDOVERS[0] } });
    const select = await screen.findByLabelText("Stage");
    const options = within(select).getAllByRole("option").map((o) => o.textContent);
    expect(options).toEqual(["Farm", "FPO", "Pack-house", "Cold storage"]); // not Retail / Transport
    await userEvent.selectOptions(select, "PACKHOUSE");
    await userEvent.type(screen.getByLabelText("Location"), "Chiplun");
    await userEvent.click(screen.getByRole("button", { name: /sign & record/i }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST" && c.path.endsWith("/handover"))).toBe(true));
    expect(calls.find((c) => c.path.endsWith("/handover"))?.body).toMatchObject({ stage: "PACKHOUSE", location: "Chiplun" });
    expect(await screen.findByText("Hand-over signed and recorded")).toBeInTheDocument();
  });

  it("gives the exporter RETAIL", async () => {
    renderPage(<Custody />, { path: "/custody/:id", route: `/custody/${ID}`, role: "exporter", routes });
    const select = await screen.findByLabelText("Stage");
    expect(within(select).getAllByRole("option").map((o) => o.textContent)).toEqual(["Cold storage", "Retail"]);
  });

  it("surfaces a broken hand-over from verification", async () => {
    const bad = verification("TAMPERED");
    bad.handovers = [{ id: 1, stage: "FARM", anchored: true, ledger_ref: "local:3", ok: false, problems: ["content does not match its hash (edited)"], organisation: "x", at: "" }];
    renderPage(<Custody />, { path: "/custody/:id", route: `/custody/${ID}`, routes: { ...routes, [`GET /api/verify/${ID}`]: bad } });
    expect(await screen.findByText("content does not match its hash (edited)")).toBeInTheDocument();
    expect(screen.getByText("chain broken")).toBeInTheDocument();
  });
});

describe("Verify / ledger", () => {
  const base = { ...shipmentRoutes, "GET /api/ledger/status": { backend: "local", decentralised: false, integrity_ok: true, entries: 12, problem: "" }, "GET /api/ledger/entries": [{ ref: "local:1", kind: "BATCH", payload: { merkle_root: "a1".repeat(32) }, ts: 1_791_000_000, prev_hash: "", hash: "h" }], "GET /api/demo/status": { enabled: true } };

  it("shows Verified with per-batch roots and is honest that the demo ledger is single-party", async () => {
    renderPage(<Verify />, { path: "/verify/:id", route: `/verify/${ID}`, routes: { ...base, [`GET /api/verify/${ID}`]: verification("VERIFIED") } });
    expect(await screen.findByText("Verified ✓")).toBeInTheDocument();
    expect(screen.getAllByText("verified ✓").length).toBe(2);
    expect(screen.getByText("single-party demo ledger")).toBeInTheDocument();
    expect(screen.getByText(/run by one party/)).toBeInTheDocument();
    expect(screen.getAllByText("a1a1a1a1a1…a1a1").length).toBeGreaterThan(0);
  });

  it("shows Tamper detected with the exact problems", async () => {
    renderPage(<Verify />, { path: "/verify/:id", route: `/verify/${ID}`, routes: { ...base, [`GET /api/verify/${ID}`]: verification("TAMPERED") } });
    expect(await screen.findByText("Tamper detected ✗")).toBeInTheDocument();
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("displayed temp_c (6.0) differs from the signed body");
    expect(alert).toHaveTextContent("Merkle root mismatch");
    expect(screen.getByText("tampered ✗")).toBeInTheDocument();
  });

  it("calls the partial state partial", async () => {
    renderPage(<Verify />, { path: "/verify/:id", route: `/verify/${ID}`, routes: { ...base, [`GET /api/verify/${ID}`]: verification("PARTIAL") } });
    expect(await screen.findByText("Verified (partial) ✓")).toBeInTheDocument();
    expect(screen.getByText(/5 newest record\(s\) not yet anchored/)).toBeInTheDocument();
  });

  it("re-verifies on demand, and tamper tools exist only for admins when enabled", async () => {
    const { calls } = renderPage(<Verify />, { path: "/verify/:id", route: `/verify/${ID}`, routes: { ...base, [`GET /api/verify/${ID}`]: verification("VERIFIED"), "POST /api/demo/tamper": { tampered: { seq: 3 }, next: "" } } });
    await screen.findByText("Verified ✓");
    const before = calls.filter((c) => c.path === `/api/verify/${ID}`).length;
    await userEvent.click(screen.getByRole("button", { name: /verify now/i }));
    await waitFor(() => expect(calls.filter((c) => c.path === `/api/verify/${ID}`).length).toBeGreaterThan(before));
    await userEvent.click(await screen.findByRole("button", { name: "Edit a shown value" }));
    await waitFor(() => expect(calls.find((c) => c.path === "/api/demo/tamper")?.body).toEqual({ shipment_id: ID, kind: "edit_value" }));
  });

  it("hides demo tools from non-admins", async () => {
    renderPage(<Verify />, { path: "/verify/:id", route: `/verify/${ID}`, role: "fpo", routes: { ...base, [`GET /api/verify/${ID}`]: verification("VERIFIED") } });
    await screen.findByText("Verified ✓");
    expect(screen.queryByText(/Demo tools/)).not.toBeInTheDocument();
  });
});

describe("Devices", () => {
  const devices = [
    { id: "HUB-0001", kind: "hub", name: "", hub_id: null, shipment_id: ID, key_epoch: 0, firmware_version: "sim-0.1.0", battery_pct: 88, last_seen_at: new Date().toISOString(), online: false, backlog: 12, offline_since: 1_791_000_100, last_seq: 50, last_hash: "" },
    { id: "TAG-0001", kind: "tag", name: "", hub_id: "HUB-0001", shipment_id: ID, key_epoch: 1, firmware_version: "", battery_pct: 15, last_seen_at: null, online: false, backlog: 0, offline_since: null, last_seq: null, last_hash: null },
  ];
  it("lists hubs and tags with battery, status and key epoch", async () => {
    renderPage(<Devices />, { routes: { "GET /api/devices": devices, "GET /api/shipments": [SHIPMENT] } });
    expect(await screen.findByText("HUB-0001")).toBeInTheDocument();
    expect(screen.getByText("TAG-0001")).toBeInTheDocument();
    expect(screen.getByText("Offline")).toBeInTheDocument();
    expect(screen.getByText("never seen")).toBeInTheDocument();
    expect(screen.getAllByRole("meter").map((m) => m.getAttribute("aria-valuenow"))).toEqual(["88", "15"]);
  });
  it("lets an admin rotate a key and shows it once", async () => {
    renderPage(<Devices />, { routes: { "GET /api/devices": devices, "GET /api/shipments": [SHIPMENT], "POST /api/devices/TAG-0001/rotate-key": { device: devices[1], key_epoch: 2, device_key_hex: "9f".repeat(32) } } });
    const row = (await screen.findByText("TAG-0001")).closest("tr") as HTMLElement;
    await userEvent.click(within(row).getByRole("button", { name: "Rotate key" }));
    expect(await screen.findByTestId("device-key")).toHaveTextContent("9f".repeat(32));
  });
  it("hides provisioning from FPO operators but lets them pair tags", async () => {
    renderPage(<Devices />, { role: "fpo", routes: { "GET /api/devices": devices, "GET /api/shipments": [SHIPMENT] } });
    await screen.findByText("TAG-0001");
    expect(screen.queryByRole("button", { name: "Add device" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Rotate key" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Pair to shipment" })).toBeInTheDocument();
  });
});

describe("Simulator control", () => {
  const run = {
    id: "abc123", scenario: "demo_full", title: "Full demo", hub_id: "HUB-0001", tag_ids: ["TAG-0001", "TAG-0002"], shipment_id: ID, food_type: "mango", profile: "demo", accel: 120, state: "running", error: null,
    duration_min: 260, pending_steps: [{ at: 55, action: "network_cut", params: {} }],
    snapshot: { elapsed_min: 30, temperature: 18.2, ethylene_index: 42, flap: 50, fan: true, connected: false, backlog: 35, battery: 93, led: "blue", buzzer_latched: false, lat: 17, lon: 73, truth_risk: 41.5 },
    log: ["T+12m INJECT heat +12 C"], simulated: true,
  };
  const routes = {
    "GET /api/simulator/scenarios": { scenarios: [{ name: "demo_full", title: "Full demo", description: "everything", food_type: "mango", duration_min: 260, profile: "demo", accel: 60, steps: [{ at: 12, action: "heat", params: {} }] }], injections: ["heat"] },
    "GET /api/simulator/state": { runs: [run] },
    "POST /api/simulator/runs": run,
    "POST /api/simulator/runs/abc123/inject": run,
  };
  it("labels everything as simulated and shows the live run", async () => {
    renderPage(<SimulatorControl />, { routes });
    const card = await screen.findByTestId("run-abc123");
    expect(within(card).getAllByText("SIMULATED").length).toBeGreaterThan(0);
    expect(card).toHaveTextContent("18.2 °C");
    expect(within(card).getByText("Offline")).toBeInTheDocument();
    expect(card).toHaveTextContent("T+55m network_cut");
    expect(screen.getAllByText("SIMULATED").length).toBeGreaterThan(1);
  });
  it("starts scenarios and injects events through the API", async () => {
    const { calls } = renderPage(<SimulatorControl />, { routes });
    const card = await screen.findByTestId("run-abc123");
    await userEvent.click(within(card).getByRole("button", { name: "Heat +12 °C" }));
    await waitFor(() => expect(calls.find((c) => c.path === "/api/simulator/runs/abc123/inject")?.body).toEqual({ action: "heat", params: { extra_c: 12 } }));
    await userEvent.click(screen.getByRole("button", { name: "Start run" }));
    await waitFor(() => expect(calls.find((c) => c.method === "POST" && c.path === "/api/simulator/runs")?.body).toMatchObject({ scenario: "demo_full", hub_id: "HUB-0001", profile: "demo" }));
  });
  it("reports an unreachable simulator", async () => {
    renderPage(<SimulatorControl />, { routes: { "GET /api/simulator/scenarios": new Response(JSON.stringify({ detail: "simulator not reachable" }), { status: 503 }), "GET /api/simulator/state": new Response("{}", { status: 503 }) } });
    expect((await screen.findAllByRole("alert"))[0]).toHaveTextContent("simulator not reachable");
  });
});

describe("Layout", () => {
  class FakeSocket {
    onopen: (() => void) | null = null;
    onmessage: ((e: { data: string }) => void) | null = null;
    onclose: (() => void) | null = null;
    onerror: (() => void) | null = null;
    close() {}
  }
  it("shows role-appropriate navigation", async () => {
    vi.stubGlobal("WebSocket", FakeSocket);
    renderPage(<Layout>hi</Layout>, { role: "driver", routes: {} });
    await screen.findByText("Fleet", { selector: "a" });
    const nav = screen.getByRole("navigation", { name: "Main" });
    expect(within(nav).getByText("Alerts & reroute")).toBeInTheDocument();
    expect(within(nav).queryByText("Devices")).not.toBeInTheDocument();
    expect(within(nav).queryByText("Simulator")).not.toBeInTheDocument();
    vi.unstubAllGlobals();
  });
  it("gives admins the simulator and devices", async () => {
    vi.stubGlobal("WebSocket", FakeSocket);
    renderPage(<Layout>hi</Layout>, { role: "admin", routes: {} });
    const nav = await screen.findByRole("navigation", { name: "Main" });
    await waitFor(() => expect(within(nav).getByText("Simulator")).toBeInTheDocument());
    expect(within(nav).getByText("Devices")).toBeInTheDocument();
    vi.unstubAllGlobals();
  });
});

describe("Shared components", () => {
  it("renders the gauge accessibly, including the empty state", () => {
    const { rerender } = renderPage(<RiskGauge risk={45} />, { role: null });
    expect(screen.getByRole("meter")).toHaveAttribute("aria-valuenow", "45");
    expect(screen.getByRole("meter").getAttribute("aria-valuetext")).toContain("WARNING");
    rerender(<RiskGauge risk={null} />);
  });
  it("badges communicate state in words, not just colour", () => {
    renderPage(
      <div>
        <LevelBadge level="CRITICAL" latched />
        <SyncBadge online={false} backlog={0} offlineSince={1_791_000_000} />
        <SyncBadge online backlog={5} />
        <SyncBadge online backlog={0} />
        <TrustBadge status="TAMPERED" />
      </div>,
      { role: null },
    );
    expect(screen.getByText("CRITICAL")).toBeInTheDocument();
    expect(screen.getByText(/latched/)).toBeInTheDocument();
    expect(screen.getByText(/^Offline/)).toBeInTheDocument();
    expect(screen.getByText("Syncing 5")).toBeInTheDocument();
    expect(screen.getByText("Online")).toBeInTheDocument();
    expect(screen.getByText("Tamper detected ✗")).toBeInTheDocument();
  });
  it("lets responders (not exporters) acknowledge warnings in the feed", async () => {
    const routes = { "POST /api/events/3/ack": { ...EVENTS[0], acknowledged_by: "admin" } };
    const { unmount } = renderPage(<EventFeed events={EVENTS} />, { role: "admin", routes });
    await screen.findAllByRole("button", { name: "Acknowledge" });
    expect(screen.getAllByRole("button", { name: "Acknowledge" })).toHaveLength(2); // info events have none
    unmount();
    renderPage(<EventFeed events={EVENTS} />, { role: "exporter", routes });
    await screen.findAllByText(/lid opened/i);
    expect(screen.queryByRole("button", { name: "Acknowledge" })).not.toBeInTheDocument();
  });
});

// keep the RISK fixture referenced so the type stays exercised
void RISK;
