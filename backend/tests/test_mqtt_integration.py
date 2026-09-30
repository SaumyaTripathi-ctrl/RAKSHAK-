"""End-to-end MQTT over TLS against the real Mosquitto from docker-compose.

Skipped unless the broker is up (``docker compose up -d mosquitto``) and Docker is reachable (used once to
read the dev CA out of the ``rakshak_certs`` volume). Run with: ``pytest -m integration``.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import ssl
import subprocess
from pathlib import Path

import aiomqtt
import pytest
import pytest_asyncio
from rakshak.db.models import Device, Record
from rakshak.main import create_app
from sqlalchemy import func, select

from .conftest import make_settings
from .helpers import T0, FakeDevice

pytestmark = pytest.mark.integration

CA_CACHE = Path(__file__).resolve().parents[2] / ".cache" / "dev-ca.crt"
SHIP = "RKS-26-000001"


def _fetch_ca() -> Path | None:
    if not shutil.which("docker"):
        return None
    try:
        out = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "-v",
                "rakshak_certs:/c:ro",
                "alpine:3.20",
                "cat",
                "/c/ca.crt",
            ],
            capture_output=True,
            timeout=60,
            check=True,
        ).stdout
    except Exception:
        return None
    CA_CACHE.parent.mkdir(exist_ok=True)
    CA_CACHE.write_bytes(out)
    return CA_CACHE


def _broker_up() -> bool:
    import socket

    try:
        with socket.create_connection(("localhost", 8883), timeout=1):
            return True
    except OSError:
        return False


@pytest.fixture(scope="module")
def ca_file():
    if not _broker_up():
        pytest.skip("mosquitto not running on localhost:8883")
    ca = _fetch_ca()
    if ca is None:
        pytest.skip("cannot read dev CA from docker volume rakshak_certs")
    return str(ca)


def device_client(ca: str, hub: str, client_id: str | None = None) -> aiomqtt.Client:
    return aiomqtt.Client(
        "localhost",
        8883,
        username=hub,
        password=f"dev-hub-{hub[-4:]}",
        identifier=client_id or f"test-{hub}",
        tls_params=aiomqtt.TLSParameters(ca_certs=ca, cert_reqs=ssl.CERT_REQUIRED),
    )


async def wait_for(predicate, timeout=10.0):
    end = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < end:
        if await predicate():
            return True
        await asyncio.sleep(0.1)
    return False


@pytest_asyncio.fixture
async def live_app(ca_file, tmp_path):
    settings = make_settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'it.db'}",
        mqtt_enabled=True,
        mqtt_ca_file=ca_file,
        mqtt_client_id=f"rakshak-api-test-{tmp_path.name[-8:]}",
    )
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        await app.state.bridge.wait_connected(10)
        yield app


async def count_records(app, device_id):
    async with app.state.db.session_factory() as s:
        return (
            await s.execute(
                select(func.count()).select_from(Record).where(Record.device_id == device_id)
            )
        ).scalar_one()


async def test_telemetry_over_tls_ingested_and_acl_enforced(live_app, ca_file):
    tag = FakeDevice("TAG-0001", SHIP)
    intruder = FakeDevice("TAG-0004", "RKS-26-000002")
    async with device_client(ca_file, "HUB-0001") as c:
        await c.publish(
            "rakshak/HUB-0001/events",
            json.dumps({"type": "status", "online": True, "fw": "0.1.0"}),
            qos=1,
        )
        for i in range(3):
            await c.publish("rakshak/HUB-0001/telemetry", tag.tag(T0 + 60 * i, temp=12 + i), qos=1)
        # ACL: HUB-0001 must not be able to publish under HUB-0002's prefix (broker silently drops it)
        await c.publish("rakshak/HUB-0002/telemetry", intruder.tag(T0), qos=1)

    assert await wait_for(lambda: _is(count_records(live_app, "TAG-0001"), 3))
    await asyncio.sleep(0.5)
    assert await count_records(live_app, "TAG-0004") == 0
    async with live_app.state.db.session_factory() as s:
        hub = await s.get(Device, "HUB-0001")
        assert hub.online and hub.firmware_version == "0.1.0"


async def _is(coro, value):
    return (await coro) == value


async def test_commands_reach_the_hub_over_mqtt(live_app, ca_file):
    got: list[dict] = []
    async with device_client(ca_file, "HUB-0002") as dev:
        await dev.subscribe("rakshak/HUB-0002/cmd", qos=1)

        async def listen():
            async for m in dev.messages:
                got.append(json.loads(m.payload))
                return

        task = asyncio.create_task(listen())
        client = __import__("httpx").AsyncClient(
            transport=__import__("httpx").ASGITransport(app=live_app), base_url="http://t"
        )
        async with client:
            tok = (
                await client.post(
                    "/api/auth/login", json={"username": "admin", "password": "admin123"}
                )
            ).json()["access_token"]
            r = await client.post(
                "/api/devices/HUB-0002/cmd",
                json={"cmd": "FLAP_SET", "arg": 100},
                headers={"Authorization": f"Bearer {tok}"},
            )
            assert r.status_code == 202 and r.json()["status"] == "SENT"
        await asyncio.wait_for(task, 5)
    assert got[0]["cmd"] == "FLAP_SET" and got[0]["arg"] == 100 and got[0]["source"] == "user:admin"


async def test_persistent_session_queues_qos1_while_backend_is_down(ca_file, tmp_path):
    """The offline story in miniature: backend down -> hub publishes -> backend returns -> nothing lost."""
    cid = f"rakshak-api-persist-{tmp_path.name[-8:]}"
    mk = lambda: create_app(  # noqa: E731
        make_settings(
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'p.db'}",
            mqtt_enabled=True,
            mqtt_ca_file=ca_file,
            mqtt_client_id=cid,
        )
    )
    tag = FakeDevice("TAG-0001", SHIP)
    app1 = mk()
    async with app1.router.lifespan_context(app1):
        await app1.state.bridge.wait_connected(10)
        async with device_client(ca_file, "HUB-0001") as c:
            await c.publish("rakshak/HUB-0001/telemetry", tag.tag(T0), qos=1)
        assert await wait_for(lambda: _is(count_records(app1, "TAG-0001"), 1))
    # backend is now DOWN; hub keeps publishing a backlog
    async with device_client(ca_file, "HUB-0001") as c:
        for i in range(1, 6):
            await c.publish("rakshak/HUB-0001/telemetry", tag.tag(T0 + 60 * i), qos=1)
    app2 = mk()
    async with app2.router.lifespan_context(app2):
        await app2.state.bridge.wait_connected(10)
        assert await wait_for(lambda: _is(count_records(app2, "TAG-0001"), 6), timeout=15)
        async with app2.state.db.session_factory() as s:
            assert (await s.get(Device, "TAG-0001")).last_seq == 5
