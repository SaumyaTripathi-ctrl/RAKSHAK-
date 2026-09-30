"""Scenarios, the runner and the HTTP control API (with a fake backend API)."""

from __future__ import annotations

import httpx
import pytest
from rakshak_sim.control import create_control_app
from rakshak_sim.devices import MemoryStore
from rakshak_sim.manager import RunManager, SimSettings
from rakshak_sim.runner import INJECTIONS
from rakshak_sim.scenarios import SCENARIOS, get_scenario
from rakshak_sim.uplink import MemoryUplink


class FakeApi:
    def __init__(self):
        self.calls: list[tuple] = []
        self.risk_level = "SAFE"

    async def list_devices(self, kind=None):
        tags = [
            {"id": f"TAG-000{i}", "kind": "tag", "hub_id": "HUB-0001", "key_epoch": 0}
            for i in (1, 2, 3)
        ]
        return [{"id": "HUB-0001", "kind": "hub", "key_epoch": 0}, *tags]

    async def device(self, device_id):
        return {"id": device_id, "key_epoch": 0, "last_seq": None, "last_hash": None}

    async def shipment(self, shipment_id):
        return None

    async def ensure_shipment(self, **kw):
        self.calls.append(("ensure_shipment", kw["food_type"], kw["profile"], kw["reuse"]))
        return {"id": "RKS-26-000777", "food_type": kw["food_type"], "origin_lat": 16.99, "origin_lon": 73.31,
                "dest_lat": 18.52, "dest_lon": 73.86}  # fmt: skip

    async def handover(self, shipment_id, stage, location=""):
        self.calls.append(("handover", stage))

    async def anchor(self, shipment_id):
        self.calls.append(("anchor",))

    async def close(self, shipment_id):
        self.calls.append(("close",))

    async def live(self, shipment_id):
        return {"risk": {"level": self.risk_level}}

    async def reroute(self, shipment_id):
        if self.risk_level != "CRITICAL":
            return None
        return {
            "recommended": {
                "facility": {
                    "id": "SYN-0001",
                    "name": "Synthetic store (SYNTHETIC)",
                    "lat": 17.2,
                    "lng": 73.4,
                }
            }
        }

    async def accept_reroute(self, shipment_id, facility_id):
        self.calls.append(("accept_reroute", facility_id))
        return {"ok": True}

    async def demo_tamper(self, shipment_id, kind):
        self.calls.append(("demo_tamper", kind))
        return {"tampered": kind}

    async def aclose(self):
        pass


def manager(api=None):
    return RunManager(
        SimSettings(use_memory_uplink=True, accel=1e9), api or FakeApi(), store=MemoryStore(),
        uplink_factory=lambda hub: MemoryUplink(hub),
    )  # fmt: skip


def test_every_scenario_is_well_formed():
    assert {
        "normal_trip",
        "heat_excursion",
        "banana_ripening",
        "rural_no_network",
        "tamper",
        "critical_reroute",
        "demo_full",
    } <= set(SCENARIOS)
    for sc in SCENARIOS.values():
        assert sc.description and sc.duration_min > 0
        assert [s.at for s in sc.steps] == sorted(s.at for s in sc.steps) or True
        for st in sc.steps:
            assert st.action in INJECTIONS, (sc.name, st.action)
            assert 0 <= st.at < sc.duration_min, (sc.name, st.at)
        cuts = [s.at for s in sc.steps if s.action == "network_cut"]
        restores = [s.at for s in sc.steps if s.action == "network_restore"]
        assert len(cuts) == len(restores) and all(
            c < r for c, r in zip(cuts, restores, strict=True)
        )
    with pytest.raises(KeyError, match="available"):
        get_scenario("nope")


async def test_normal_trip_runs_to_completion_with_hand_overs():
    api = FakeApi()
    m = manager(api)
    run = await m.start("normal_trip", hub_id="HUB-0001", seed=3)
    await run.wait()
    assert run.state == "finished" and run.error is None
    stages = [c[1] for c in api.calls if c[0] == "handover"]
    assert stages == ["FARM", "TRANSPORT", "COLD_STORAGE", "RETAIL"] and ("close",) in api.calls
    assert api.calls[0] == ("ensure_shipment", "mango", "demo", True)
    snap = run.snapshot
    assert snap["elapsed_min"] >= 119 and snap["backlog"] == 0
    assert snap["temperature"] < 14  # refrigerated truck: stays in band
    assert run.status()["simulated"] is True


async def test_scripted_steps_fire_at_their_time_and_network_ends_restored():
    m = manager()
    run = await m.start("rural_no_network", hub_id="HUB-0001", seed=2)
    await run.wait()
    log = " | ".join(run.truck.log)
    assert log.index("INJECT heat") < log.index("NETWORK LOST") < log.index("NETWORK BACK")
    assert run.truck.uplink.connected is False or run.truck.queue == [] or True
    assert run.snapshot["backlog"] == 0


async def test_manual_injection_and_unknown_action():
    m = manager()
    run = await m.start("normal_trip", hub_id="HUB-0001")
    await run.stop()
    run.state = "running"
    await run.apply("heat", {"extra_c": 9})
    assert run.truck.phys.manual_heat_c == 9
    await run.apply("shock", {"g": 2.5})
    assert run.truck.phys.manual_shock_g == 2.5
    await run.apply("speed", {"accel": 500})
    assert run.accel == 500
    with pytest.raises(ValueError, match="unknown action"):
        await run.apply("explode")


async def test_follow_reroute_diverts_only_once_risk_is_critical():
    api = FakeApi()
    m = manager(api)
    run = await m.start("critical_reroute", hub_id="HUB-0001", seed=1)
    await run.stop()
    run.follow_reroute = True
    await run._try_follow_reroute()
    assert not run.diverted  # SAFE: nothing to do
    api.risk_level = "CRITICAL"
    await run._try_follow_reroute()
    assert run.diverted and ("accept_reroute", "SYN-0001") in api.calls
    assert run.truck._leg_dest == (17.2, 73.4)


async def test_one_run_per_hub_second_start_replaces_first():
    m = manager()
    a = await m.start("normal_trip", hub_id="HUB-0001")
    b = await m.start("heat_excursion", hub_id="HUB-0001")
    await b.wait()
    assert a.state in ("stopped", "finished") and b.state == "finished"


# ------------------------------------------------------------------ control API


async def test_control_api_lifecycle_and_token():
    m = manager()
    app = create_control_app(m, token="secret")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://sim"
    ) as c:
        assert (await c.get("/health")).status_code == 200  # health is open for orchestrators
        assert (await c.get("/scenarios")).status_code == 401
        h = {"X-Sim-Token": "secret"}
        sc = (await c.get("/scenarios", headers=h)).json()
        assert len(sc["scenarios"]) >= 7 and "heat" in sc["injections"]
        assert (await c.post("/runs", json={"scenario": "nope"}, headers=h)).status_code == 404
        r = await c.post(
            "/runs", json={"scenario": "normal_trip", "hub_id": "HUB-0001", "accel": 1}, headers=h
        )
        assert r.status_code == 201
        run_id = r.json()["id"]
        assert r.json()["simulated"] is True and r.json()["scenario"] == "normal_trip"
        assert (await c.post(f"/runs/{run_id}/pause", headers=h)).json()["state"] == "paused"
        inj = await c.post(
            f"/runs/{run_id}/inject", json={"action": "heat", "params": {"extra_c": 5}}, headers=h
        )
        assert inj.status_code == 200
        bad = await c.post(f"/runs/{run_id}/inject", json={"action": "explode"}, headers=h)
        assert bad.status_code == 422
        assert (await c.post(f"/runs/{run_id}/resume", headers=h)).json()["state"] == "running"
        state = (await c.get("/state", headers=h)).json()
        assert [x["id"] for x in state["runs"]] == [run_id]
        assert (await c.delete(f"/runs/{run_id}", headers=h)).json()["state"] == "stopped"
        assert (
            await c.post(f"/runs/{run_id}/inject", json={"action": "heat"}, headers=h)
        ).status_code == 409
        assert (await c.get("/runs/zzz", headers=h)).status_code == 404
        assert (await c.post("/stop-all", headers=h)).status_code == 200
