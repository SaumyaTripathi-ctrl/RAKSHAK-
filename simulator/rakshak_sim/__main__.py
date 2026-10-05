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
import time
from contextlib import asynccontextmanager

import uvicorn

from .api import HttpApi
from .control import create_control_app
from .devices import JsonStore
from .manager import RunManager, SimSettings
from .routes import route_for
from .scenarios import get_scenario

log = logging.getLogger("rakshak.sim")


async def autoplay(
    manager: RunManager, hub_id: str, scenarios: list[str], loop: bool, route_seed: int = 0
) -> None:
    """Keep one hub busy. Waits for the backend (compose starts everything at once)."""
    await asyncio.sleep(3)
    i = 0
    while True:
        name = scenarios[i % len(scenarios)]
        while manager._busy(hub_id):  # never steal a hub from a run started by the API/demo
            await asyncio.sleep(5)
        try:
            fresh = i >= len(scenarios)  # first pass revives the seeded shipment bound to this hub
            if not fresh and manager.api is not None:  # ...but only if that shipment is still open
                try:
                    hub = await manager.api.device(hub_id)
                    sh = (
                        await manager.api.shipment(hub["shipment_id"])
                        if hub and hub.get("shipment_id")
                        else None
                    )
                    fresh = not sh or sh["status"] == "DELIVERED"
                except Exception:
                    fresh = True
            run = await manager.start(
                name,
                hub_id=hub_id,
                seed=i + 1,
                new_shipment=fresh,
                **(route_for(route_seed + i) if fresh else {}),
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


BACKFILL = (
    "normal_trip",
    "heat_excursion",
    "banana_ripening",
    "critical_reroute",
    "rural_no_network",
)


async def backfill(manager: RunManager, hub_id: str) -> None:
    """Fill an empty database with finished trips (QR pages, custody, ledger, alerts) so the UI is never blank."""
    try:
        r = await manager.api._call("GET", "/api/shipments")  # type: ignore[union-attr]
        if r.status_code == 200 and len(r.json()) >= 8:
            return
        now = int(time.time())
        for i, name in enumerate(BACKFILL):
            sc = get_scenario(name)
            run = await manager.start(
                name,
                hub_id=hub_id,
                seed=100 + i,
                new_shipment=True,
                accel=4000.0,
                start_epoch=now - int(sc.duration_min * 60) - (len(BACKFILL) - i) * 3600,
                **route_for(i + 2),
            )
            log.info("backfill %s -> %s", name, run.shipment_id)
            await run.wait()
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        log.warning("history backfill skipped: %s", exc)


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
        do_backfill = os.environ.get("SIM_BACKFILL", "true").lower() == "true"
        for n, part in enumerate(filter(None, (p.strip() for p in spec.split(",")))):
            hub, _, scen = part.partition(":")
            if do_backfill and n == 0:  # the first hub replays history before its live trips start

                async def first(hub=hub, scen=scen, n=n):
                    await asyncio.sleep(3)
                    await backfill(manager, hub)
                    await autoplay(manager, hub, scen.split("+"), loop, route_seed=n)

                tasks.append(asyncio.create_task(first()))
            else:
                tasks.append(
                    asyncio.create_task(
                        autoplay(manager, hub, scen.split("+"), loop, route_seed=n * 2)
                    )
                )
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
