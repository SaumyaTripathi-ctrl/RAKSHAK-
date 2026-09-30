"""The simulator's hub over REAL MQTT/TLS: abrupt network loss -> broker last-will -> queue -> burst sync.

Needs the docker-compose broker (see test_mqtt_integration.py); skipped otherwise.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
import pytest_asyncio
from rakshak.db.models import Event, OfflineSegment, Record
from rakshak.main import create_app
from rakshak_sim.devices import MemoryStore
from rakshak_sim.manager import RunManager, SimSettings
from rakshak_sim.uplink import MqttUplink
from sqlalchemy import func, select

from .conftest import make_settings
from .test_mqtt_integration import _broker_up, _fetch_ca

pytestmark = pytest.mark.integration
MASTER = bytes(range(32))


@pytest.fixture(scope="module")
def ca():
    if not _broker_up():
        pytest.skip("mosquitto not running on localhost:8883")
    path = _fetch_ca()
    if path is None:
        pytest.skip("cannot read the dev CA from docker")
    return str(path)


async def wait_for(pred, timeout=30.0):
    end = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < end:
        if await pred():
            return True
        await asyncio.sleep(0.2)
    return False


@pytest_asyncio.fixture
async def stack(ca, models_dir, tmp_path):
    app = create_app(
        make_settings(
            # a file DB: the in-memory test DB shares one connection, which concurrent tasks would trample
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'sim_it.db'}",
            model_dir=models_dir,
            osrm_enabled=False,
            mqtt_enabled=True,
            mqtt_ca_file=ca,
            mqtt_client_id=f"rakshak-api-sim-{uuid.uuid4().hex[:8]}",
        )
    )
    async with app.router.lifespan_context(app):
        await app.state.bridge.wait_connected(10)

        def uplink(hub: str) -> MqttUplink:
            return MqttUplink(
                hub, host="localhost", port=8883, username=hub, password=f"dev-hub-{hub[-4:]}",
                ca_file=ca, keepalive=10,
            )  # fmt: skip

        mgr = RunManager(
            SimSettings(use_memory_uplink=False, accel=1e9, master_key=MASTER),
            None,
            store=MemoryStore(),
            uplink_factory=uplink,
        )
        yield app, mgr
        await mgr.stop_all()


async def test_abrupt_drop_publishes_last_will_and_backlog_syncs_over_real_mqtt(stack):
    app, mgr = stack
    from rakshak_sim.scenarios import SCENARIOS, Scenario, Step

    sc = Scenario(  # short version of rural_no_network so the test stays quick
        "it_offline", "it", "it", "mango", duration_min=40,
        steps=(Step(10, "network_cut"), Step(25, "network_restore")),
        physics={"tau_h": 14.0, "pcm_cap0": 60.0}, handovers=False,
    )  # fmt: skip
    SCENARIOS.pop("it_offline", None)
    run = await mgr.start(sc, hub_id="HUB-0002", shipment_id="RKS-26-000002", seed=3)
    await run.wait()
    assert run.state == "finished", run.error
    total_published = 40 * 4  # 40 ticks x (hub + 3 tags)

    async def all_in():
        async with app.state.db.session_factory() as s:
            n = (await s.execute(select(func.count()).select_from(Record).where(Record.shipment_id == "RKS-26-000002"))).scalar_one()
        # minus the 3 tags x 4 ticks still buffered on the tags after the last BLE batch (every 5th tick)
        return n >= total_published - 12

    assert await wait_for(all_in), "records lost over the real broker"
    async with app.state.db.session_factory() as s:
        kinds = [e.kind for e in (await s.execute(select(Event).order_by(Event.id))).scalars() if e.kind.startswith("HUB_")]
        segs = list((await s.execute(select(OfflineSegment))).scalars())
        missing = list((await s.execute(select(Event).where(Event.kind == "MISSING_RECORDS"))).scalars())
    assert "HUB_OFFLINE" in kinds and kinds[-1] == "HUB_ONLINE"  # last-will really fired, then the reconnect
    assert len(segs) == 1 and segs[0].end_ts and segs[0].end_ts > segs[0].start_ts
    assert not missing
