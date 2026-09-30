"""Prediction end to end through the real ingest path (trained quick models; data is simulated)."""

from __future__ import annotations

import json

import pytest
import pytest_asyncio
from rakshak.db.models import Device, Event, RiskPoint
from rakshak.main import create_app
from rakshak_ml.edge import flap_for_deviation
from sqlalchemy import select

from .conftest import login, make_settings
from .helpers import T0, FakeDevice

SHIP = "RKS-26-000001"  # seeded: mango (band 10-13 C), hub HUB-0001, tags TAG-0001..0003, near Ratnagiri


class FakePublisher:
    def __init__(self):
        self.sent: list[dict] = []

    async def publish(self, topic, payload, qos=1):
        d = json.loads(payload)
        d["topic"] = topic
        self.sent.append(d)

    def cmds(self, name=None):
        return [(c["cmd"], c["arg"]) for c in self.sent if name is None or c["cmd"] == name]


@pytest_asyncio.fixture
async def papp(models_dir):
    app = create_app(make_settings(model_dir=models_dir, osrm_enabled=False))
    app.state.publisher = FakePublisher()
    async with app.router.lifespan_context(app):
        assert app.state.predictor is not None
        yield app


@pytest_asyncio.fixture
async def pclient(papp):
    import httpx

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=papp), base_url="http://t") as c:
        yield c


class Trip:
    """Feeds a hub and three tags, one sample per minute, like the simulator will."""

    def __init__(self, app, ship=SHIP, hub="HUB-0001", tags=("TAG-0001", "TAG-0002", "TAG-0003")):
        self.app, self.ship = app, ship
        self.hub = FakeDevice(hub, ship)
        self.tags = [FakeDevice(t, ship) for t in tags]
        self.t = T0
        self.upper = 13.0

    async def tick(self, temp, eth=5.0, rh=88.0, fan=False, shock=0.0, lat=16.99, lon=73.3):
        ing = self.app.state.ingestor
        for i, tag in enumerate(self.tags):
            await ing.ingest_frame(
                tag.tag(self.t, temp=temp + 0.05 * i, eth=eth, rh=rh), via_hub=self.hub.id
            )
        flap = flap_for_deviation(temp, self.upper)
        await ing.ingest_frame(
            self.hub.hub(self.t, temp=temp + 2, shock=shock, lat=lat, lon=lon, flap=flap, fan=fan),
            via_hub=self.hub.id,
        )
        self.t += 60

    async def run(self, minutes, temp_fn, **kw):
        for m in range(minutes):
            await self.tick(temp_fn(m), **kw)


async def all_events(app, kind=None):
    async with app.state.db.session_factory() as s:
        q = select(Event).order_by(Event.id)
        if kind:
            q = q.where(Event.kind == kind)
        return list((await s.execute(q)).scalars())


async def test_steady_in_band_stays_safe_and_silent(papp, pclient):
    trip = Trip(papp)
    await trip.run(40, lambda m: 11.5)
    live = papp.state.predictor.latest(SHIP)
    assert live["level"] == "SAFE" and live["risk"] < 30 and live["model_profile"] == "real"
    assert live["model_note"] == "trained on simulated data"
    assert papp.state.publisher.sent == []  # AI stays quiet when nothing is wrong
    assert [e.kind for e in await all_events(papp) if e.kind.startswith("ALERT")] == []
    async with papp.state.db.session_factory() as s:
        pts = list((await s.execute(select(RiskPoint).order_by(RiskPoint.t))).scalars())
    assert 35 <= len(pts) <= 40 and all(p.level == 0 for p in pts)
    adm = await login(pclient, "admin")
    api = (await pclient.get(f"/api/shipments/{SHIP}/risk", headers=adm)).json()
    assert len(api["points"]) == len(pts)
    live_api = (await pclient.get(f"/api/shipments/{SHIP}/live", headers=adm)).json()
    assert live_api["risk"]["level"] == "SAFE"


async def test_heat_trip_end_to_end(papp, pclient):
    admin = await login(pclient, "admin")
    r = await pclient.put(
        f"/api/shipments/{SHIP}/model-profile", json={"model_profile": "demo"}, headers=admin
    )
    assert r.status_code == 200
    pub: FakePublisher = papp.state.publisher
    trip = Trip(papp)

    await trip.run(20, lambda m: 11.5)  # calm start
    assert papp.state.predictor.latest(SHIP)["level"] == "SAFE"

    ramp = lambda m: min(11.5 + 0.6 * m, 24.0)  # noqa: E731  warms to 24 C and stays there
    levels, risks = [], []
    for m in range(240):
        await trip.tick(ramp(m), eth=8.0)
        live = papp.state.predictor.latest(SHIP)
        levels.append(live["level"])
        risks.append(live["risk"])
        if live["level"] == "CRITICAL":
            break
    assert levels[-1] == "CRITICAL", "sustained heat must end up CRITICAL"
    assert "WARNING" in levels and levels.index("WARNING") < levels.index(
        "CRITICAL"
    )  # escalates steadily
    assert risks[-1] >= 70 and risks[-1] > risks[0] + 30
    live = papp.state.predictor.latest(SHIP)
    assert live["model_profile"] == "demo" and live["latched"] is True
    assert live["rsl_hours"] < 24 and any(
        "above the 13 °C limit" in d["text"] for d in live["drivers"]
    )

    # --- events: AI alerts in order, with numbers
    await papp.state.predictor.wait_idle()
    kinds = [
        e.kind
        for e in await all_events(papp)
        if e.data.get("source") == "ai" or e.kind == "REROUTE"
    ]
    assert kinds.index("ALERT_WARNING") < kinds.index("ALERT_CRITICAL") < kinds.index("REROUTE")
    crit = (await all_events(papp, "ALERT_CRITICAL"))[-1]
    assert crit.severity == "critical" and crit.data["risk"] >= 70 and crit.data["drivers"]

    # --- AI commands to the hub: floors and alert tiers, each sent once
    assert pub.cmds("FLAP_SET") == [("FLAP_SET", 50), ("FLAP_SET", 100)]
    assert [c for c in pub.cmds() if c[0].startswith("ALERT")] == [
        ("ALERT_WARNING", None),
        ("ALERT_CRITICAL", None),
    ]
    assert all(c["topic"] == "rakshak/HUB-0001/cmd" and c["source"] == "ai" for c in pub.sent)
    n_before = len(pub.sent)
    for _ in range(5):  # staying CRITICAL does not spam the hub
        await trip.tick(24.0, eth=8.0)
    assert len(pub.sent) == n_before

    # --- reroute: compatible, near the truck (Ratnagiri), road routing disabled -> labelled estimate
    rr = (await pclient.get(f"/api/shipments/{SHIP}/reroute", headers=admin)).json()
    best = rr["recommended"]
    assert (
        best["facility"]["data_source"] == "synthetic" and "(SYNTHETIC)" in best["facility"]["name"]
    )
    assert (
        best["facility"]["storage_min"] <= 14 and best["facility"]["storage_max"] >= 9
    )  # mango-compatible
    assert best["routing_source"] == "haversine" and best["routing_status"] == "estimated"
    assert best["distance_km"] < 150 and rr["origin"]["lat"] == pytest.approx(16.99)
    assert len(rr["alternatives"]) <= 2 and "compatible" in rr["reason"]
    reroute_events = await all_events(papp, "REROUTE")
    assert reroute_events and reroute_events[0].data["facility_id"] == best["facility"]["id"]

    # --- accept the detour (driver), wrong facility rejected, exporter forbidden
    driver, exporter = await login(pclient, "driver"), await login(pclient, "exporter")
    assert (
        await pclient.post(
            f"/api/shipments/{SHIP}/reroute/accept",
            json={"facility_id": "SYN-9999"},
            headers=driver,
        )
    ).status_code == 404
    assert (
        await pclient.post(
            f"/api/shipments/{SHIP}/reroute/accept",
            json={"facility_id": best["facility"]["id"]},
            headers=exporter,
        )
    ).status_code == 403
    ok = await pclient.post(
        f"/api/shipments/{SHIP}/reroute/accept",
        json={"facility_id": best["facility"]["id"]},
        headers=driver,
    )
    assert ok.status_code == 200
    assert papp.state.predictor.latest(SHIP)["reroute"]["accepted"] is True

    # --- fleet overview reflects the AI level
    truck = next(
        t
        for t in (await pclient.get("/api/fleet/overview", headers=admin)).json()["trucks"]
        if t["shipment_id"] == SHIP
    )
    assert truck["level"] == 2 and truck["risk"]["level"] == "CRITICAL"

    # --- acknowledge the latched alarm: hub gets ACK_ALERT, latch clears
    ev = (
        await pclient.get(f"/api/events?shipment_id={SHIP}&kind=ALERT_CRITICAL", headers=driver)
    ).json()[0]
    assert (await pclient.post(f"/api/events/{ev['id']}/ack", headers=exporter)).status_code == 403
    assert (await pclient.post(f"/api/events/{ev['id']}/ack", headers=driver)).status_code == 200
    assert papp.state.predictor.latest(SHIP)["latched"] is False
    assert ("ACK_ALERT", None) in pub.cmds()
    assert papp.state.predictor.latest(SHIP)["level"] == "CRITICAL"  # silenced, not recovered


async def test_ethylene_triggers_fan_command_when_ripening_and_warning(papp):
    await papp.state.db.create_all()
    from rakshak.db.models import Shipment

    async with papp.state.db.session_factory() as s:
        (await s.get(Shipment, SHIP)).model_profile = "demo"
        await s.commit()
    pub = papp.state.publisher
    trip = Trip(papp)
    await trip.run(15, lambda m: 11.5, eth=5)
    for m in range(240):
        await trip.tick(min(11.5 + 0.6 * m, 22.0), eth=min(10 + m * 1.0, 90))
        if papp.state.predictor.latest(SHIP)["level"] != "SAFE" and ("FAN_ON", None) in pub.cmds():
            break
    assert (
        "FAN_ON",
        None,
    ) in pub.cmds()  # ethylene-sensitive food + WARNING + high index -> scrubber forced on


async def test_backlog_replay_is_not_steered_but_is_recorded(papp):
    async with papp.state.db.session_factory() as s:
        hub = await s.get(Device, "HUB-0001")
        hub.backlog = 12  # hub is still draining its offline queue
        from rakshak.db.models import Shipment

        (await s.get(Shipment, SHIP)).model_profile = "demo"
        await s.commit()
    trip = Trip(papp)
    await trip.run(10, lambda m: 11.5)
    for m in range(200):
        await trip.tick(min(11.5 + 0.8 * m, 26.0))
        if papp.state.predictor.latest(SHIP)["level"] == "CRITICAL":
            break
    assert papp.state.predictor.latest(SHIP)["level"] == "CRITICAL"
    await papp.state.predictor.wait_idle()
    assert papp.state.publisher.sent == []  # stale conditions: no commands to the hub
    assert (await all_events(papp, "REROUTE")) == []  # and no detour for an old excursion
    crit = (await all_events(papp, "ALERT_CRITICAL"))[0]
    assert crit.data["historical"] is True  # but the event is recorded, marked as historical


async def test_state_is_rebuilt_after_restart(papp):
    trip = Trip(papp)
    await trip.run(30, lambda m: 11.5 + (4 if m > 15 else 0))
    before = dict(papp.state.predictor.latest(SHIP))
    papp.state.predictor.trackers.clear()  # simulate a process restart
    await trip.tick(15.5)
    after = papp.state.predictor.latest(SHIP)
    assert after["level"] == before["level"]
    assert after["risk"] == pytest.approx(before["risk"], abs=6)
    assert after["t"] > before["t"]


async def test_unknown_food_type_and_missing_models_degrade_gracefully(models_dir, tmp_path):
    from rakshak.db.models import Shipment

    app = create_app(make_settings(model_dir=models_dir, osrm_enabled=False))
    async with app.router.lifespan_context(app):
        async with app.state.db.session_factory() as s:
            (await s.get(Shipment, SHIP)).food_type = "durian"
            await s.commit()
        trip = Trip(app)
        await trip.run(5, lambda m: 30.0)
        assert app.state.predictor.latest(SHIP) is None  # no band, no prediction, no crash

    empty = create_app(make_settings(model_dir=str(tmp_path)))
    async with empty.router.lifespan_context(empty):
        import httpx

        assert empty.state.predictor is None
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=empty), base_url="http://t"
        ) as c:
            h = (await c.get("/health")).json()
            assert h["prediction"] == {"enabled": True, "active": False, "profiles": []}
            adm = await login(c, "admin")
            live = (await c.get(f"/api/shipments/{SHIP}/live", headers=adm)).json()
            assert live["risk"] is None
            assert (await c.get(f"/api/shipments/{SHIP}/reroute", headers=adm)).status_code == 503
        await Trip(empty).run(3, lambda m: 11.5)  # ingest keeps working without models


async def test_food_types_and_facilities_endpoints(pclient):
    adm = await login(pclient, "admin")
    types = (await pclient.get("/api/food-types", headers=adm)).json()
    assert {t["food_type"] for t in types} == {
        "mango",
        "banana",
        "tomato",
        "leafy_vegetables",
        "milk",
    }
    assert all(t["verification_status"] == "TODO-verify" and t["source"] for t in types)
    fac = (
        await pclient.get(
            "/api/facilities?food_type=milk&lat=23.0&lon=72.6&radius_km=100", headers=adm
        )
    ).json()
    assert fac["data_sources"] == ["synthetic"] and fac["count"] > 0
    assert all(f["storage_min"] <= 5 for f in fac["facilities"])  # milk-compatible only
    assert (await pclient.get("/api/facilities?food_type=durian", headers=adm)).status_code == 422
    assert (await pclient.get("/api/food-types")).status_code == 401


async def test_model_profile_endpoint_is_admin_only(pclient):
    fpo = await login(pclient, "fpo")
    assert (
        await pclient.put(
            f"/api/shipments/{SHIP}/model-profile", json={"model_profile": "demo"}, headers=fpo
        )
    ).status_code == 403
    adm = await login(pclient, "admin")
    assert (
        await pclient.put(
            f"/api/shipments/{SHIP}/model-profile", json={"model_profile": "bogus"}, headers=adm
        )
    ).status_code == 422
    body = (await pclient.get(f"/api/shipments/{SHIP}", headers=adm)).json()
    assert body["model_profile"] == "real"
