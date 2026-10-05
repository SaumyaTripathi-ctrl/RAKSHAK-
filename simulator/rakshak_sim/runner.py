"""Executing a scenario: paces ticks, fires scripted and manual injections, talks to the backend API."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
import uuid
from dataclasses import dataclass, field

from .api import ApiClient
from .scenarios import Scenario, Step
from .truck import VirtualTruck

log = logging.getLogger("rakshak.sim.run")

INJECTIONS = (
    "heat",
    "ethylene",
    "shock",
    "spike",
    "lid_open",
    "lid_close",
    "reboot_tag",
    "ble_drop",
    "ble_restore",
    "network_cut",
    "network_restore",
    "tamper_forge",
    "tamper_delete",
    "tamper_db",
    "follow_reroute",
    "anchor",
    "handover",
    "speed",
)


@dataclass
class Run:
    scenario: Scenario
    truck: VirtualTruck
    shipment_id: str
    api: ApiClient | None = None
    accel: float = 60.0
    run_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    loop_forever: bool = False

    state: str = "created"  # created | running | paused | finished | stopped | error
    error: str | None = None
    snapshot: dict = field(default_factory=dict)
    follow_reroute: bool = False
    diverted: bool = False
    _steps: list[Step] = field(default_factory=list)
    _stop: asyncio.Event = field(default_factory=asyncio.Event)
    _paused: bool = False
    _task: asyncio.Task | None = None
    _started_real: float = 0.0
    _did_transport: bool = False

    def __post_init__(self) -> None:
        self._steps = sorted(self.scenario.steps, key=lambda s: s.at)

    # ---------------------------------------------------------------- lifecycle
    def start(self) -> None:
        self._task = asyncio.create_task(self._main(), name=f"sim-run-{self.run_id}")

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await asyncio.wait_for(self._task, 5)
            if not self._task.done():
                self._task.cancel()
        if self.state in ("running", "paused", "created"):
            self.state = "stopped"

    async def wait(self) -> None:
        if self._task:
            await self._task

    def pause(self, paused: bool = True) -> None:
        self._paused = paused
        self.state = "paused" if paused else "running"

    # ---------------------------------------------------------------- main loop
    async def _main(self) -> None:
        try:
            self.state = "running"
            self._started_real = time.monotonic()
            await self.truck.connect()
            if self.api and self.scenario.handovers:
                await self.api.handover(self.shipment_id, "FARM", "Farm gate (simulated)")
            await self._loop()
            await self._finish()
        except asyncio.CancelledError:
            self.state = "stopped"
            raise
        except Exception as exc:
            log.exception("run %s failed", self.run_id)
            self.state, self.error = "error", str(exc)
        finally:
            with contextlib.suppress(Exception):
                await self.truck.uplink.close()

    async def _loop(self) -> None:
        tr = self.truck
        while not self._stop.is_set():
            if self._paused:
                await asyncio.sleep(0.2)
                continue
            t0 = time.monotonic()
            while self._steps and self._steps[0].at <= tr.elapsed_min:
                step = self._steps.pop(0)
                await self.apply(step.action, step.params)
            if (
                self.api
                and self.scenario.handovers
                and not self._did_transport
                and tr.elapsed_min >= 5
            ):
                self._did_transport = True
                await self.api.handover(
                    self.shipment_id, "TRANSPORT", "Loaded, departing (simulated)"
                )
            if self.follow_reroute and tr.tick_no % 3 == 0:
                await self._try_follow_reroute()
            self.snapshot = await tr.tick()
            if tr.elapsed_min >= self.scenario.duration_min or (
                self.diverted and tr.arrived and not self._steps
            ):
                return
            pace = tr.cfg.sample_s / max(self.accel, 1e-6)
            await asyncio.sleep(max(0.0, pace - (time.monotonic() - t0)))

    async def _finish(self) -> None:
        tr = self.truck
        if not tr.uplink.connected:
            await tr.network_restore()
        for _ in range(200):  # drain whatever is still queued
            if not tr.queue:
                break
            await tr._flush()
        if self.api and self.scenario.handovers and not self._stop.is_set():
            await self.api.handover(
                self.shipment_id, "COLD_STORAGE", "Cold store arrival (simulated)"
            )
            await self.api.handover(self.shipment_id, "RETAIL", "Retail delivery (simulated)")
            await self.api.close(self.shipment_id)
        self.snapshot = tr.snapshot()
        if self.state != "stopped":
            self.state = "finished"

    # ---------------------------------------------------------------- injections
    async def apply(self, action: str, params: dict | None = None) -> str:
        p, tr = params or {}, self.truck
        if action == "heat":
            tr.inject_heat(p.get("extra_c", 12))
        elif action == "ethylene":
            tr.inject_ethylene(p.get("units_per_h", 30))
        elif action == "shock":
            tr.inject_shock(p.get("g", 2.0))
        elif action == "spike":
            tr.inject_spike(p.get("extra_c", 6))
        elif action == "lid_open":
            tr.lid_open(p.get("tag_id"))
        elif action == "lid_close":
            tr.lid_close(p.get("tag_id"))
        elif action == "reboot_tag":
            tr.reboot_tag(p.get("tag_id"))
        elif action == "ble_drop":
            tr.ble_drop(p.get("tag_id"), up=False)
        elif action == "ble_restore":
            tr.ble_drop(p.get("tag_id"), up=True)
        elif action == "network_cut":
            await tr.network_cut()
        elif action == "network_restore":
            await tr.network_restore()
        elif action == "tamper_forge":
            tr.tamper_forge(p.get("device_id"), int(p.get("count", 1)))
        elif action == "tamper_delete":
            tr.tamper_delete(p.get("device_id"), int(p.get("count", 1)))
        elif action == "tamper_db":
            res = (
                await self.api.demo_tamper(self.shipment_id, p.get("kind", "edit_value"))
                if self.api
                else None
            )
            tr.note(f"DB TAMPER via demo tools: {res}")
        elif action == "follow_reroute":
            self.follow_reroute = True
            tr.note("driver will follow the AI detour once risk is CRITICAL")
        elif action == "anchor":
            if self.api:
                await self.api.anchor(self.shipment_id)
            tr.note("records anchored on the ledger")
        elif action == "handover":
            if self.api:
                await self.api.handover(self.shipment_id, p.get("stage", "TRANSPORT"))
        elif action == "speed":
            self.accel = max(0.1, float(p.get("accel", self.accel)))
        else:
            raise ValueError(f"unknown action {action!r}; available: {', '.join(INJECTIONS)}")
        return "ok"

    async def _try_follow_reroute(self) -> None:
        if not self.api or self.diverted:
            return
        live = await self.api.live(self.shipment_id)
        risk = (live or {}).get("risk") or {}
        if risk.get("level") != "CRITICAL":
            return
        doc = await self.api.reroute(self.shipment_id)
        best = (doc or {}).get("recommended")
        if not best:
            return
        fac = best["facility"]
        await self.api.accept_reroute(self.shipment_id, fac["id"])
        path = best.get("geometry")
        if not path:
            route_fn = getattr(self.api, "route", None)
            if route_fn is not None:
                here = self.truck.position()
                try:
                    path = ((await route_fn(here, (fac["lat"], fac["lng"]))) or {}).get("geometry")
                except Exception:
                    path = None
        self.truck.divert((fac["lat"], fac["lng"]), path)
        self.truck.note(f"driver accepted the detour to {fac['name']}")
        self.diverted = True
        self.follow_reroute = False

    # ---------------------------------------------------------------- status
    def status(self) -> dict:
        tr = self.truck
        return {
            "id": self.run_id,
            "scenario": self.scenario.name,
            "title": self.scenario.title,
            "hub_id": tr.cfg.hub_id,
            "tag_ids": tr.cfg.tag_ids,
            "shipment_id": self.shipment_id,
            "food_type": tr.cfg.food_type,
            "profile": tr.cfg.profile,
            "accel": self.accel,
            "state": self.state,
            "error": self.error,
            "duration_min": self.scenario.duration_min,
            "pending_steps": [
                {"at": s.at, "action": s.action, "params": s.params} for s in self._steps
            ],
            "follow_reroute": self.follow_reroute,
            "diverted": self.diverted,
            "snapshot": self.snapshot or tr.snapshot(),
            "log": tr.log[-25:],
            "simulated": True,
        }
