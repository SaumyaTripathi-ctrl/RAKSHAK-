"""``python -m rakshak_sim``: control server + optional autoplay of scenarios on the seeded trucks.

Environment (all optional): RAKSHAK_API_URL, RAKSHAK_MASTER_KEY_HEX, MQTT_HOST/PORT/CA_FILE, MQTT_DEVICE_USERS,
SIM_DATA_DIR, SIM_ACCEL, SIM_PORT (8100), SIM_TOKEN, SIM_AUTOSTART ("HUB-0001:normal_trip,HUB-0002:banana_ripening"),
SIM_LOOP (true: restart the scenario when a trip ends).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
from contextlib import asynccontextmanager

import uvicorn

from .api import HttpApi
from .control import create_control_app
from .devices import JsonStore
from .manager import RunManager, SimSettings

log = logging.getLogger("rakshak.sim")


async def autoplay(manager: RunManager, hub_id: str, scenarios: list[str], loop: bool) -> None:
    """Keep one hub busy. Waits for the backend (compose starts everything at once)."""
    await asyncio.sleep(3)
    i = 0
    while True:
        name = scenarios[i % len(scenarios)]
        while manager._busy(hub_id):  # never steal a hub from a run started by the API/demo
            await asyncio.sleep(5)
        try:
            run = await manager.start(
                name, hub_id=hub_id, seed=i + 1, new_shipment=i >= len(scenarios)
            )
            log.info(
                "autoplay %s on %s -> run %s (shipment %s)",
                name,
                hub_id,
                run.run_id,
                run.shipment_id,
            )
            await run.wait()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.warning("autoplay %s/%s failed (%s); retrying in 10 s", hub_id, name, exc)
            await asyncio.sleep(10)
            continue
        i += 1
        if not loop and i >= len(scenarios):
            return
        await asyncio.sleep(5)


def build_app():
    settings = SimSettings.from_env()
    api = HttpApi(settings.api_url)
    manager = RunManager(
        settings, api, store=JsonStore(os.path.join(settings.data_dir, "devices.json"))
    )
    tasks: list[asyncio.Task] = []

    @asynccontextmanager
    async def lifespan(_app):
        spec = os.environ.get("SIM_AUTOSTART", "")
        loop = os.environ.get("SIM_LOOP", "true").lower() != "false"
        for part in filter(None, (p.strip() for p in spec.split(","))):
            hub, _, scen = part.partition(":")
            tasks.append(asyncio.create_task(autoplay(manager, hub, scen.split("+"), loop)))
        try:
            yield
        finally:
            for t in tasks:
                t.cancel()
            for t in tasks:
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await t
            await manager.stop_all()
            await api.aclose()

    app = create_control_app(manager, os.environ.get("SIM_TOKEN"))
    app.router.lifespan_context = lifespan
    return app


def main() -> None:
    logging.basicConfig(
        level=os.environ.get("SIM_LOG", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    uvicorn.run(
        build_app(),
        host="0.0.0.0",
        port=int(os.environ.get("SIM_PORT", "8100")),
        log_level="warning",
        loop="asyncio",  # aiomqtt uses loop.add_writer, which uvloop rejects for closed sockets
    )


if __name__ == "__main__":
    main()
