from __future__ import annotations

import asyncio
import sys

import pytest
from rakshak.codec import decode_frame_with_master, peek_header
from rakshak_sim.devices import MemoryStore
from rakshak_sim.truck import TruckConfig, VirtualTruck
from rakshak_sim.uplink import MemoryUplink

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

MASTER = bytes(range(32))
T0 = 1_791_000_000


class Collector:
    """Stands in for the broker + backend: records everything the hub publishes."""

    def __init__(self) -> None:
        self.frames: list[tuple[str, bytes]] = []
        self.events: list[dict] = []

    async def sink(self, topic: str, payload: bytes) -> None:
        import json

        if topic.endswith("/telemetry"):
            self.frames.append((topic, payload))
        elif topic.endswith("/events"):
            self.events.append(json.loads(payload))

    def decoded(self, device_id: str | None = None):
        out = []
        for _, f in self.frames:
            d = decode_frame_with_master(f, MASTER) if peek_header(f) else None
            if device_id is None or d.header.device_id == device_id:
                out.append(d)
        return out


def make_truck(food="mango", *, tags=3, hub="HUB-0001", physics=None, profile="demo", **kw):
    col = Collector()
    uplink = MemoryUplink(hub, col.sink)
    cfg = TruckConfig(
        hub_id=hub,
        tag_ids=[f"TAG-{i:04d}" for i in range(1, tags + 1)],
        shipment_id="RKS-26-000001",
        food_type=food,
        master_key=MASTER,
        origin=(16.99, 73.31),
        dest=(18.52, 73.86),
        start_epoch=T0,
        profile=profile,
        trip_minutes=120,
        ambient=12.5,
        physics=physics or {"tau_h": 10.0, "pcm_cap0": 45.0},
        **kw,
    )
    store = MemoryStore()
    truck = VirtualTruck(cfg, uplink, store)
    return truck, uplink, col, store


@pytest.fixture
def rig():
    return make_truck


async def run_ticks(truck: VirtualTruck, n: int) -> None:
    for _ in range(n):
        await truck.tick()
