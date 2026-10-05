"""HTTP API: auth & roles, shipments, devices, commands, custody, public QR endpoint, websocket."""

from __future__ import annotations

import json

import pytest
from rakshak.codec import derive_device_key
from rakshak.codec import spec as S
from rakshak.main import create_app
from starlette.testclient import TestClient

from .conftest import login, make_settings
from .helpers import MASTER, T0, FakeDevice

SHIP = "RKS-26-000001"


class FakePublisher:
    def __init__(self):
        self.sent: list[tuple[str, dict]] = []

    async def publish(self, topic, payload, qos=1):
        self.sent.append((topic, json.loads(payload)))


async def test_health_and_docs(client):
    r = await client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok" and body["mqtt"] == {"enabled": False, "connected": False}
    paths = (await client.get("/openapi.json")).json()["paths"]
    for p in (
        "/api/shipments",
        "/api/devices",
        "/api/events",
        "/api/public/shipments/{shipment_id}",
        "/api/fleet/overview",
    ):
        assert p in paths


async def test_login_and_me(client):
    bad = await client.post("/api/auth/login", json={"username": "admin", "password": "nope"})
    assert bad.status_code == 401
    h = await login(client, "driver")
    me = (await client.get("/api/auth/me", headers=h)).json()
    assert me["role"] == "driver" and me["username"] == "driver"


async def test_endpoints_require_auth(client):
    for path in (
        "/api/shipments",
        "/api/devices",
        "/api/events",
        "/api/fleet/overview",
        "/api/auth/me",
    ):
        assert (await client.get(path)).status_code == 401, path
    assert (
        await client.get("/api/shipments", headers={"Authorization": "Bearer garbage"})
    ).status_code == 401


async def test_create_shipment_roles(client, admin, fpo):
    body = {"food_type": "tomato", "weight_kg": 500, "hub_id": "HUB-0001", "tag_ids": ["TAG-0001"]}
    driver = await login(client, "driver")
    assert (await client.post("/api/shipments", json=body, headers=driver)).status_code == 403
    r = await client.post("/api/shipments", json=body, headers=fpo)
    assert r.status_code == 201
    sid = r.json()["id"]
    assert sid.startswith("RKS-") and sid.endswith("000004")  # 3 demo shipments exist
    live = (await client.get(f"/api/shipments/{sid}/live", headers=fpo)).json()
    assert live["hub"]["device_id"] == "HUB-0001" and [t["device_id"] for t in live["tags"]] == [
        "TAG-0001"
    ]
    bad = await client.post("/api/shipments", json={**body, "hub_id": "NOPE"}, headers=fpo)
    assert bad.status_code == 422
    assert (await client.get("/api/shipments/RKS-26-999999", headers=fpo)).status_code == 404


async def test_live_timeline_fleet_after_ingest(app, client, fpo):
    ing = app.state.ingestor
    hub, tag1, tag2 = (
        FakeDevice("HUB-0001", SHIP),
        FakeDevice("TAG-0001", SHIP),
        FakeDevice("TAG-0002", SHIP),
    )
    for i in range(4):
        t = T0 + 60 * i
        await ing.ingest_frame(
            hub.hub(t, temp=26, lat=16.99 + i * 0.01, flap=25, alert=1 if i == 3 else 0),
            via_hub="HUB-0001",
        )
        await ing.ingest_frame(tag1.tag(t, temp=10 + i, eth=20 + i), via_hub="HUB-0001")
        await ing.ingest_frame(tag2.tag(t, temp=12 + i, eth=30 + i), via_hub="HUB-0001")
    live = (await client.get(f"/api/shipments/{SHIP}/live", headers=fpo)).json()
    assert live["hub"]["flap_pct"] == 25 and live["hub"]["alert_level"] == 1
    assert live["hub"]["lat"] == pytest.approx(17.02)
    assert live["aggregates"]["temp_c"] == pytest.approx((13 + 15) / 2)
    assert live["aggregates"]["ethylene_idx"] == pytest.approx(33.0)
    assert live["sync"]["backlog"] == 0
    tl = (await client.get(f"/api/shipments/{SHIP}/timeline", headers=fpo)).json()
    assert (
        len(tl["hub"]) == 4 and set(tl["tags"]) == {"TAG-0001", "TAG-0002"} and len(tl["gps"]) == 4
    )
    assert tl["hub"][0]["t"] == T0
    fleet = (await client.get("/api/fleet/overview", headers=fpo)).json()
    assert fleet["kpis"]["active_shipments"] == 3 and fleet["kpis"]["at_risk"] == 1
    truck = next(t for t in fleet["trucks"] if t["shipment_id"] == SHIP)
    assert truck["level"] == 1 and truck["lat"] == pytest.approx(17.02)
    since = (
        await client.get(f"/api/shipments/{SHIP}/timeline?since={T0 + 120}", headers=fpo)
    ).json()
    assert len(since["hub"]) == 2


async def test_events_feed_and_ack(app, client, fpo):
    ing = app.state.ingestor
    tag = FakeDevice("TAG-0001", SHIP)
    await ing.ingest_frame(tag.event(T0, S.EventCode.LID_OPEN))
    evs = (await client.get(f"/api/events?shipment_id={SHIP}&unacked=true", headers=fpo)).json()
    assert [e["kind"] for e in evs] == ["LID_OPEN"]
    exporter = await login(client, "exporter")
    assert (
        await client.post(f"/api/events/{evs[0]['id']}/ack", headers=exporter)
    ).status_code == 403
    acked = (await client.post(f"/api/events/{evs[0]['id']}/ack", headers=fpo)).json()
    assert acked["acknowledged_by"] == "fpo"
    assert (await client.get("/api/events?unacked=true", headers=fpo)).json() == []


async def test_device_provisioning_and_rotation(client, admin, fpo):
    r = await client.post("/api/devices", json={"id": "TAG-0042", "kind": "tag"}, headers=fpo)
    assert r.status_code == 403  # only admins mint device keys
    r = await client.post(
        "/api/devices", json={"id": "TAG-0042", "kind": "tag", "hub_id": "HUB-0001"}, headers=admin
    )
    assert r.status_code == 201
    assert r.json()["device_key_hex"] == derive_device_key(MASTER, "TAG-0042", 0).hex()
    assert (
        await client.post("/api/devices", json={"id": "TAG-0042", "kind": "tag"}, headers=admin)
    ).status_code == 409
    assert (
        await client.post("/api/devices", json={"id": "bad id", "kind": "tag"}, headers=admin)
    ).status_code == 422
    rot = (await client.post("/api/devices/TAG-0042/rotate-key", headers=admin)).json()
    assert (
        rot["key_epoch"] == 1
        and rot["device_key_hex"] == derive_device_key(MASTER, "TAG-0042", 1).hex()
    )
    listing = (await client.get("/api/devices?kind=hub", headers=fpo)).json()
    assert [d["id"] for d in listing] == ["HUB-0001", "HUB-0002", "HUB-0003"]
    assert "device_key_hex" not in json.dumps(listing)


async def test_commands_published_and_acked(app, client, admin):
    pub = FakePublisher()
    app.state.publisher = pub
    r = await client.post(
        "/api/devices/HUB-0001/cmd", json={"cmd": "FLAP_SET", "arg": 50}, headers=admin
    )
    assert r.status_code == 202 and r.json()["status"] == "SENT"
    topic, payload = pub.sent[0]
    assert topic == "rakshak/HUB-0001/cmd" and payload["cmd"] == "FLAP_SET" and payload["arg"] == 50
    assert payload["source"] == "user:admin"
    for bad in ({"cmd": "FLAP_SET", "arg": 33}, {"cmd": "FLAP_SET"}, {"cmd": "SELF_DESTRUCT"}):
        assert (
            await client.post("/api/devices/HUB-0001/cmd", json=bad, headers=admin)
        ).status_code == 422
    assert (
        await client.post("/api/devices/HUB-9999/cmd", json={"cmd": "FAN_ON"}, headers=admin)
    ).status_code == 422
    exporter = await login(client, "exporter")
    assert (
        await client.post("/api/devices/HUB-0001/cmd", json={"cmd": "FAN_ON"}, headers=exporter)
    ).status_code == 403
    await app.state.ingestor.handle_hub_event(
        "HUB-0001", {"type": "cmd_ack", "id": payload["id"], "ok": True}
    )
    evs = (await client.get("/api/events?kind=COMMAND", headers=admin)).json()
    assert len(evs) == 1 and "acked" in evs[0]["message"]


async def test_command_fails_visibly_when_mqtt_disabled(client, admin):
    r = await client.post("/api/devices/HUB-0001/cmd", json={"cmd": "FAN_ON"}, headers=admin)
    assert r.status_code == 202 and r.json()["status"] == "FAILED"


async def test_handover_roles_chain_and_signature(client, fpo):
    from rakshak.services.custody import verify_handovers  # noqa: F401

    driver = await login(client, "driver")
    exporter = await login(client, "exporter")
    post = lambda h, stage, **kw: client.post(  # noqa: E731
        f"/api/shipments/{SHIP}/handover", json={"stage": stage, "location": "x", **kw}, headers=h
    )
    assert (await post(fpo, "RETAIL")).status_code == 403  # fpo cannot sign RETAIL
    assert (await post(driver, "FARM")).status_code == 403
    assert (await post(fpo, "NOT_A_STAGE")).status_code == 403
    a = (await post(fpo, "FARM", lat=16.99, lon=73.3)).json()
    b = (await post(fpo, "PACKHOUSE")).json()
    c = (await post(driver, "TRANSPORT")).json()
    d = (await post(exporter, "RETAIL")).json()
    assert a["prev_hash"] == "00" * 32 and b["prev_hash"] == a["payload_hash"]
    assert c["prev_hash"] == b["payload_hash"] and d["prev_hash"] == c["payload_hash"]
    assert a["public_key"] == b["public_key"] != c["public_key"]  # per-actor keys
    timeline = (await client.get(f"/api/shipments/{SHIP}/custody", headers=fpo)).json()
    assert [h["stage"] for h in timeline] == ["FARM", "PACKHOUSE", "TRANSPORT", "RETAIL"]
    evs = (await client.get(f"/api/events?shipment_id={SHIP}&kind=HANDOVER", headers=fpo)).json()
    assert len(evs) == 4


async def test_handover_verification_detects_edit(app, client, fpo):
    from rakshak.db.models import Handover
    from rakshak.services.custody import verify_handovers
    from sqlalchemy import select

    for stage in ("FARM", "FPO", "PACKHOUSE"):
        await client.post(f"/api/shipments/{SHIP}/handover", json={"stage": stage}, headers=fpo)
    async with app.state.db.session_factory() as s:
        rows = list((await s.execute(select(Handover).order_by(Handover.id))).scalars())
        assert all(c.ok for c in verify_handovers(rows))
        rows[1].notes = "edited afterwards"
        assert [c.ok for c in verify_handovers(rows)] == [
            True,
            False,
            True,
        ]  # edit caught at its own row
        # An attacker who also recomputes the hash cannot forge the actor's signature and breaks the next link.
        import hashlib

        from rakshak.services.custody import canonical_payload

        rows[1].payload_hash = hashlib.sha256(canonical_payload(rows[1])).hexdigest()
        checks = verify_handovers(rows)
        assert [c.ok for c in checks] == [True, False, False]
        assert "signature" in checks[1].reason and "link" in checks[2].reason
        await s.rollback()


async def test_public_endpoint_is_open_and_redacted(app, client, fpo):
    ing = app.state.ingestor
    tag = FakeDevice("TAG-0001", SHIP)
    for i in range(3):
        await ing.ingest_frame(tag.tag(T0 + 60 * i, temp=11 + i))
    await client.post(
        f"/api/shipments/{SHIP}/handover",
        json={"stage": "FARM", "location": "Ratnagiri"},
        headers=fpo,
    )
    r = await client.get(f"/api/public/shipments/{SHIP}")  # no Authorization header
    assert r.status_code == 200
    doc = r.json()
    assert doc["food_type"] == "mango" and doc["summary"]["temp_max_c"] == 13.0
    assert doc["journey"][0]["stage"] == "FARM" and doc["journey"][0]["organisation"].startswith(
        "Konkan"
    )
    text = json.dumps(doc)
    for secret in (
        "username",
        "actor",
        "Ramesh",
        "public_key",
        "signature",
        "password",
        "device_key",
        "TAG-0001",
    ):
        assert secret not in text, secret
    assert (await client.get("/api/public/shipments/RKS-26-404040")).status_code == 404


def test_websocket_live_push(tmp_path):
    settings = make_settings(database_url=f"sqlite+aiosqlite:///{tmp_path / 't.db'}")
    app = create_app(settings)
    with TestClient(app) as tc:
        token = tc.post(
            "/api/auth/login", json={"username": "admin", "password": "admin123"}
        ).json()["access_token"]
        with pytest.raises(Exception):  # noqa: B017  (bad token: server closes with 4401)
            with tc.websocket_connect("/ws?token=bad"):
                pass
        with tc.websocket_connect(f"/ws?token={token}&shipment_id={SHIP}") as ws:
            assert ws.receive_json()["type"] == "hello"
            app.state.realtime.publish(
                {"type": "event", "data": {"x": 1}}, "OTHER-SHIPMENT"
            )  # filtered out
            app.state.realtime.publish({"type": "event", "data": {"x": 2}}, SHIP)
            msg = ws.receive_json()
            assert msg == {"type": "event", "data": {"x": 2}}


async def test_concurrent_shipment_creation_gets_unique_ids(client, admin):
    """Several clients creating shipments at once must all succeed with distinct ids (was a 500 on id collision)."""
    import asyncio

    body = {"food_type": "mango", "weight_kg": 10, "model_profile": "real"}
    rs = await asyncio.gather(
        *[client.post("/api/shipments", json=body, headers=admin) for _ in range(8)]
    )
    assert [r.status_code for r in rs] == [201] * 8
    assert len({r.json()["id"] for r in rs}) == 8
