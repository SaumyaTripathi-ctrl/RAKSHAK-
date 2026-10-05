"""Run manager: builds trucks from the backend's devices/shipments and keeps the active runs."""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable
from dataclasses import dataclass

from rakshak_ml.bands import get_band

from .api import ApiClient
from .devices import DeviceStore, MemoryStore
from .runner import Run
from .scenarios import Scenario, get_scenario
from .truck import TruckConfig, VirtualTruck
from .uplink import MemoryUplink, MqttUplink, Uplink

log = logging.getLogger("rakshak.sim.manager")

DEFAULT_TAGS = {"HUB-0001": ["TAG-0001", "TAG-0002", "TAG-0003"],
                "HUB-0002": ["TAG-0004", "TAG-0005", "TAG-0006"],
                "HUB-0003": ["TAG-0007", "TAG-0008", "TAG-0009"]}  # fmt: skip


@dataclass
class SimSettings:
    api_url: str = "http://localhost:8000"
    master_key: bytes = bytes(range(32))
    mqtt_host: str = "localhost"
    mqtt_port: int = 8883
    mqtt_ca: str | None = None
    mqtt_tls: bool = True
    hub_passwords: dict[str, str] | None = None  # hub_id -> password
    data_dir: str = "./sim-data"
    accel: float | None = None  # override every scenario's speed
    use_memory_uplink: bool = False

    @classmethod
    def from_env(cls) -> SimSettings:
        users = {}
        for pair in os.environ.get("MQTT_DEVICE_USERS", "").split(","):
            if ":" in pair:
                u, pw = pair.split(":", 1)
                users[u] = pw
        return cls(
            api_url=os.environ.get("RAKSHAK_API_URL", "http://localhost:8000"),
            master_key=bytes.fromhex(
                os.environ.get("RAKSHAK_MASTER_KEY_HEX", bytes(range(32)).hex())
            ),
            mqtt_host=os.environ.get("MQTT_HOST", "localhost"),
            mqtt_port=int(os.environ.get("MQTT_PORT", "8883")),
            mqtt_ca=os.environ.get("MQTT_CA_FILE"),
            mqtt_tls=os.environ.get("MQTT_TLS", "true").lower() != "false",
            hub_passwords=users or None,
            data_dir=os.environ.get("SIM_DATA_DIR", "./sim-data"),
            accel=float(os.environ["SIM_ACCEL"]) if os.environ.get("SIM_ACCEL") else None,
        )


class RunManager:
    def __init__(
        self,
        settings: SimSettings,
        api: ApiClient | None,
        *,
        store: DeviceStore | None = None,
        uplink_factory: Callable[[str], Uplink] | None = None,
    ) -> None:
        self.s, self.api = settings, api
        self.store = store or MemoryStore()
        self._uplink_factory = uplink_factory
        self.runs: dict[str, Run] = {}

    def _uplink(self, hub_id: str) -> Uplink:
        if self._uplink_factory:
            return self._uplink_factory(hub_id)
        if self.s.use_memory_uplink:
            return MemoryUplink(hub_id)
        pw = (self.s.hub_passwords or {}).get(hub_id) or f"dev-hub-{hub_id[-4:]}"
        return MqttUplink(
            hub_id,
            host=self.s.mqtt_host,
            port=self.s.mqtt_port,
            username=hub_id,
            password=pw,
            ca_file=self.s.mqtt_ca,
            tls=self.s.mqtt_tls,
        )

    async def _resume_state(self, device_id: str) -> dict | None:
        """If our local chain state is gone, continue from what the backend has seen."""
        if self.store.load(device_id) or self.api is None:
            return None
        d = await self.api.device(device_id)
        if d and d.get("last_seq") is not None and d.get("last_hash"):
            return {
                "seq": d["last_seq"] + 1,
                "prev_hash": d["last_hash"],
                "key_epoch": d["key_epoch"],
            }
        if d:
            return {"seq": 0, "key_epoch": d["key_epoch"]}
        return None

    async def start(
        self,
        scenario: str | Scenario,
        *,
        hub_id: str | None = None,
        shipment_id: str | None = None,
        food_type: str | None = None,
        profile: str | None = None,
        accel: float | None = None,
        seed: int = 1,
        new_shipment: bool = False,
        start_epoch: int | None = None,
        tag_ids: list[str] | None = None,
        origin: tuple[float, float] | None = None,
        dest: tuple[float, float] | None = None,
        origin_name: str | None = None,
        dest_name: str | None = None,
    ) -> Run:
        sc = get_scenario(scenario) if isinstance(scenario, str) else scenario
        hub_id = hub_id or next((h for h in DEFAULT_TAGS if not self._busy(h)), "HUB-0001")
        for r in list(self.runs.values()):  # one run per hub
            if r.truck.cfg.hub_id == hub_id and r.state in ("running", "paused", "created"):
                await r.stop()
        profile = profile or sc.profile

        shipment: dict = {}
        if self.api is not None and shipment_id is None:
            devs = await self.api.list_devices()
            tags = tag_ids or [
                d["id"] for d in devs if d["kind"] == "tag" and d.get("hub_id") == hub_id
            ]
            tags = tags or DEFAULT_TAGS.get(hub_id, ["TAG-0001"])
            shipment = await self.api.ensure_shipment(
                hub_id=hub_id,
                tag_ids=tags,
                food_type=food_type or sc.food_type,
                profile=profile,
                origin=origin or sc.origin,
                dest=dest or sc.dest,
                origin_name=origin_name,
                dest_name=dest_name,
                reuse=not new_shipment,
            )
            shipment_id = shipment["id"]
        else:
            tags = tag_ids or DEFAULT_TAGS.get(hub_id, ["TAG-0001", "TAG-0002", "TAG-0003"])
            if shipment_id is None:
                raise ValueError("shipment_id is required when no backend API is configured")
        food = shipment.get("food_type") or food_type or sc.food_type
        band = get_band(food)
        o = origin or sc.origin or _pt(shipment, "origin") or (16.9902, 73.3120)
        d = dest or sc.dest or _pt(shipment, "dest") or (18.5204, 73.8567)
        physics = dict(sc.physics)
        path = None
        route_fn = getattr(self.api, "route", None)
        if (
            route_fn is not None
        ):  # road geometry so the truck drives the real road, not a ruler line
            try:
                doc = await route_fn(o, d)
                geom = (doc or {}).get("geometry") or []
                path = [(p[0], p[1]) for p in geom] if len(geom) >= 2 else None
            except Exception:  # routing is cosmetic: never block a run on it
                path = None

        for dev_id in (hub_id, *tags):
            resume = await self._resume_state(dev_id)
            if resume:
                self.store.save(dev_id, resume)

        cfg = TruckConfig(
            hub_id=hub_id,
            tag_ids=list(tags),
            shipment_id=shipment_id,
            food_type=food,
            master_key=self.s.master_key,
            origin=o,
            dest=d,
            start_epoch=start_epoch or int(time.time()),
            profile=profile,
            seed=seed,
            trip_minutes=sc.duration_min,
            physics=physics,
            ambient=sc.ambient if sc.ambient is not None else band.mid_temp + 1.0,
            has_pcm=sc.has_pcm,
            has_scrubber=sc.has_scrubber,
            path=path,
        )
        truck = VirtualTruck(cfg, self._uplink(hub_id), self.store)
        run = Run(sc, truck, shipment_id, self.api, accel=accel or self.s.accel or sc.accel)
        self.runs[run.run_id] = run
        run.start()
        return run

    def _busy(self, hub_id: str) -> bool:
        return any(
            r.truck.cfg.hub_id == hub_id and r.state in ("running", "paused", "created")
            for r in self.runs.values()
        )

    async def stop(self, run_id: str) -> bool:
        run = self.runs.get(run_id)
        if run is None:
            return False
        await run.stop()
        return True

    async def stop_all(self) -> None:
        for r in list(self.runs.values()):
            await r.stop()

    def status(self) -> dict:
        return {"runs": [r.status() for r in self.runs.values()], "simulated": True}


def _pt(shipment: dict, prefix: str) -> tuple[float, float] | None:
    lat, lon = shipment.get(f"{prefix}_lat"), shipment.get(f"{prefix}_lon")
    return (lat, lon) if lat is not None and lon is not None else None
