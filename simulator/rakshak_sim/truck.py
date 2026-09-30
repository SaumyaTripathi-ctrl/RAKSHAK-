"""One virtual truck: a hub + N crate tags on a simulated trip.

Per tick (one sample period of *device time*, 60 s by default):
  physics step -> every tag samples (T/RH every tick, strip every ``strip_every`` ticks) -> tags hand their frames to
  the hub in BLE batches -> the hub applies its NO-NETWORK edge rules (PCM flap, scrubber fan) -> hub sample ->
  encrypted, hash-chained frames go into the store-and-forward queue -> published oldest-first when 4G is up.

Commands from the backend (FLAP_SET floor, FAN_ON/OFF, ALERT_*, ACK_ALERT) arrive over MQTT and are applied here
with the semantics the firmware implements (see docs/PROTOCOL.md).
"""

from __future__ import annotations

import json
import logging
import math
from collections import deque
from dataclasses import dataclass, field

import numpy as np
from rakshak.codec import Event, EventCode, HubSample, TagSample
from rakshak.codec import spec as S
from rakshak_ml.edge import FanController, flap_for_deviation
from rakshak_ml.sim import ShipmentSim, SimConfig

from .devices import DeviceStore, MemoryStore, SimDevice
from .uplink import Uplink, UplinkDown

log = logging.getLogger("rakshak.sim.truck")

FIRMWARE = "sim-0.1.0"
AVG_SPEED_KMH = 45.0
LED = {0: "green", 1: "blue", 2: "red"}


def haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dphi, dlmb = p2 - p1, math.radians(b[1] - a[1])
    h = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * 6371.0088 * math.asin(math.sqrt(h))


@dataclass
class TruckConfig:
    hub_id: str
    tag_ids: list[str]
    shipment_id: str
    food_type: str
    master_key: bytes
    origin: tuple[float, float]
    dest: tuple[float, float]
    start_epoch: int
    profile: str = "demo"  # physics time scale: "demo" compresses time 24x, "real" does not
    seed: int = 1
    sample_s: int = 60
    strip_every: int = 5
    ble_every: int = 5
    status_every: int = 5
    burst: int = 400  # frames published per tick while draining a backlog
    trip_minutes: float | None = None  # default: distance / 45 km/h
    physics: dict = field(
        default_factory=dict
    )  # overrides of ShipmentSim attributes (tau_h, pcm_cap0, ...)
    ambient: float | None = (
        27.0  # constant ambient (makes scenarios reproducible); None = weather model
    )
    has_pcm: bool = True
    has_scrubber: bool | None = None  # default: installed for ethylene-sensitive foods


class SimTag:
    def __init__(self, dev: SimDevice, offset_c: float) -> None:
        self.dev = dev
        self.offset = offset_c
        self.eth = 0.0
        self.temp = 0.0
        self.rh = 0.0
        self.lid_open = False
        self.buffer: deque[bytes] = (
            deque()
        )  # frames not yet handed to the hub (deleted only after the hub ACK)
        self.ble_up = True
        self.synced = True
        self.boot_epoch: int | None = None  # device time of the last reboot while unsynced
        self.batt = 100.0


class VirtualTruck:
    def __init__(self, cfg: TruckConfig, uplink: Uplink, store: DeviceStore | None = None) -> None:
        from rakshak_ml.bands import get_band

        self.cfg, self.uplink = cfg, uplink
        self.store = store or MemoryStore()
        self.band = get_band(cfg.food_type)
        scrubber = self.band.ethylene_sensitive if cfg.has_scrubber is None else cfg.has_scrubber
        ts = 24.0 if cfg.profile == "demo" else 1.0
        self.phys = ShipmentSim(
            SimConfig(
                cfg.food_type,
                duration_h=24.0,
                step_min=cfg.sample_s / 60.0,
                time_scale=ts,
                seed=cfg.seed,
                shipment_id=cfg.shipment_id,
                heat_excursions=0,
                has_pcm=cfg.has_pcm,
                has_scrubber=scrubber,
                mixed_load_ethylene=0.0,
                reading_spikes=[],
                ambient_override=cfg.ambient,
            )
        )
        self.phys.begin()
        for k, v in cfg.physics.items():
            setattr(self.phys, k, v)
        self.phys.life_mult = cfg.physics.get("life_mult", 1.0)
        self.rng = np.random.default_rng(cfg.seed + 7)

        self.hub = SimDevice(cfg.hub_id, cfg.master_key, self.store)
        self.tags = [
            SimTag(SimDevice(t, cfg.master_key, self.store), float(self.rng.normal(0, 0.25)))
            for t in cfg.tag_ids
        ]
        self.queue: deque[tuple[str, bytes]] = deque()  # (topic, payload)
        self.t = cfg.start_epoch  # device clock (epoch seconds)
        self.tick_no = 0

        # hub state
        self.flap = 0
        self.fan_on = False
        self.floor = 0  # FLAP_SET floor from AI/operator
        self.fan_forced: bool | None = None  # FAN_ON/OFF from AI/operator
        # Under demo time compression the ethylene dynamics are 24x faster, so the rule's thresholds scale with it.
        self.fan_ctl = FanController(
            rise_per_min=0.12 * ts,
            stable_eps_per_min=0.06 * ts,
            stable_min=max(30.0 / ts, 10.0),
        )
        self.ai_tier = 0
        self.edge_alert = 0
        self.buzzer_latched = False
        self.batt = 96.0
        self._low_batt_sent = False
        self.offline_since: int | None = None
        self._announce = True  # send a status message before the next publish
        self._drop_next: dict[
            str, int
        ] = {}  # device_id -> records to silently drop (tamper: deletion)
        self._forge_next: dict[
            str, int
        ] = {}  # device_id -> records to forge (tamper: edited record)
        self.log: list[str] = []

        # position
        self._leg_origin, self._leg_dest = cfg.origin, cfg.dest
        self._leg_start = cfg.start_epoch
        self._leg_minutes = cfg.trip_minutes or max(
            5.0, haversine_km(cfg.origin, cfg.dest) / AVG_SPEED_KMH * 60
        )
        self.uplink.set_command_handler(self.handle_command)

    # ------------------------------------------------------------------ position
    @property
    def elapsed_min(self) -> float:
        return (self.t - self.cfg.start_epoch) / 60.0

    def position(self) -> tuple[float, float]:
        frac = min(max((self.t - self._leg_start) / 60.0 / self._leg_minutes, 0.0), 1.0)
        (la1, lo1), (la2, lo2) = self._leg_origin, self._leg_dest
        lat, lon = la1 + (la2 - la1) * frac, lo1 + (lo2 - lo1) * frac
        bulge = 0.04 * math.sin(math.pi * frac)  # a gentle curve so the trail is not a ruler line
        return lat + bulge * (lo2 - lo1) / 3, lon - bulge * (la2 - la1) / 3

    def divert(self, dest: tuple[float, float]) -> None:
        """Follow a detour: new leg from the current position."""
        here = self.position()
        self._leg_origin, self._leg_dest, self._leg_start = here, dest, self.t
        self._leg_minutes = max(5.0, haversine_km(here, dest) / AVG_SPEED_KMH * 60)
        self.note(f"diverting to {dest[0]:.3f},{dest[1]:.3f} ({self._leg_minutes:.0f} min)")

    @property
    def arrived(self) -> bool:
        return (self.t - self._leg_start) / 60.0 >= self._leg_minutes

    def note(self, msg: str) -> None:
        self.log.append(f"T+{self.elapsed_min:.0f}m {msg}")
        del self.log[:-60]

    # ------------------------------------------------------------------ tick
    def _tag_sample(self, tag: SimTag, row: dict, strip_now: bool) -> bytes | None:
        tag.temp = row["temperature"] + tag.offset + float(self.rng.normal(0, 0.05))
        tag.rh = row["humidity"] + float(self.rng.normal(0, 0.4))
        if strip_now:
            tag.eth = float(np.clip(row["ethylene_index"] + self.rng.normal(0, 0.3), 0, 100))
        valid = tag.synced
        ts = self.t if valid else self.t - (tag.boot_epoch or self.cfg.start_epoch)
        flags = (S.TagFlags.TS_VALID if valid else 0) | (S.TagFlags.LID_OPEN if tag.lid_open else 0)

        def build(seq: int) -> TagSample:
            return TagSample(
                tag.dev.id,
                self.cfg.shipment_id,
                seq,
                int(ts),
                round(tag.temp * 100),
                round(min(tag.rh, 100) * 100),
                round(tag.eth * 10),
                int(flags),
                int(tag.batt),
            )

        return self._emit(tag.dev, build)

    def _emit(self, dev: SimDevice, build) -> bytes | None:
        """Encrypt + chain one record, honouring tamper injections. ``None`` = the record was 'lost'."""
        if self._forge_next.get(dev.id):
            self._forge_next[dev.id] -= 1
            self.note(f"TAMPER: {dev.id} sent an edited record (stale hash)")
            return dev.emit_forged(build)
        frame = dev.emit(build)
        if self._drop_next.get(dev.id):
            self._drop_next[dev.id] -= 1
            self.note(f"TAMPER: a {dev.id} record was deleted before upload")
            return None
        return frame

    def _event(
        self, dev: SimDevice, code: int, arg0: int = 0, arg1: int = 0, *, valid=True
    ) -> bytes | None:
        flags = S.TagFlags.TS_VALID if valid else 0
        batt = int(self.batt)
        ts = self.t

        def build(seq: int) -> Event:
            return Event(
                dev.id, self.cfg.shipment_id, seq, int(ts), code, arg0, arg1, int(flags), batt
            )

        return self._emit(dev, build)

    def _tag_event(self, tag: SimTag, code: int, *, valid: bool = True) -> None:
        """Tag events join the tag's own buffer so they reach the hub in chain order."""
        frame = self._event(tag.dev, code, valid=valid)
        if frame is not None:
            tag.buffer.append(frame)

    def _queue(self, frame: bytes | None, topic: str | None = None) -> None:
        if frame is not None:
            self.queue.append((topic or f"rakshak/{self.cfg.hub_id}/telemetry", frame))

    def _ble_batch(self) -> None:
        """Tags -> hub. A tag deletes its copy only after the hub ACK; out-of-range tags keep buffering."""
        for tag in self.tags:
            if not tag.ble_up:
                continue
            while tag.buffer:
                self._queue(tag.buffer.popleft())
            if (
                not tag.synced
            ):  # hub ACK carries GNSS time: tag sets its clock and logs a TIME_SYNC event
                mono = max(0, self.t - (tag.boot_epoch or self.cfg.start_epoch))
                tag.synced = True
                tag.boot_epoch = None
                self._queue(
                    self._event(tag.dev, EventCode.TIME_SYNC, mono & 0xFFFF, (mono >> 16) & 0xFFFF)
                )
                self.note(f"{tag.dev.id} clock synced by the hub")

    async def tick(self) -> dict:
        cfg = self.cfg
        row = self.phys.step(self.flap, self.fan_on)
        strip_now = self.tick_no % cfg.strip_every == 0

        for tag in self.tags:
            tag.batt = max(0.0, tag.batt - 0.0008)
            frame = self._tag_sample(tag, row, strip_now)
            if frame is not None:
                tag.buffer.append(frame)
        if self.tick_no % cfg.ble_every == 0:
            self._ble_batch()

        # ---- hub edge rules: run with NO network
        crate = sum(t.temp for t in self.tags) / len(self.tags)
        edge_flap = flap_for_deviation(crate, self.band.max_temp)
        dT = crate - self.band.max_temp
        self.edge_alert = 2 if dT >= 6 else 1 if dT >= 3 else 0
        self.flap = max(edge_flap, self.floor)
        if self.phys.has_scrubber:
            if strip_now:  # the fan rule runs on new strip readings only (every ~5 min)
                self.fan_ctl.update(
                    self.tick_no * cfg.sample_s / 60.0, max(t.eth for t in self.tags)
                )
            self.fan_on = self.fan_ctl.fan_on if self.fan_forced is None else self.fan_forced
        else:
            self.fan_on = False
        tier = max(self.edge_alert, self.ai_tier)
        if tier >= 2:
            self.buzzer_latched = True

        self.batt = max(0.0, self.batt - 0.004)
        if self.batt < 15 and not self._low_batt_sent:
            self._low_batt_sent = True
            self._queue(self._event(self.hub, EventCode.LOW_BATTERY))

        lat, lon = self.position()
        shock = row["shock_g"]
        if shock >= 1.0:
            self._queue(self._event(self.hub, EventCode.SHOCK, int(shock * 100)))

        hub_flags = int(S.HubFlags.TS_VALID | S.HubFlags.GPS_VALID) | (
            S.HubFlags.FAN_ON if self.fan_on else 0
        )

        def build_hub(seq: int) -> HubSample:
            return HubSample(
                self.hub.id,
                cfg.shipment_id,
                seq,
                int(self.t),
                round(row["external_temperature"] * 100),
                round(row["external_humidity"] * 100),
                min(65535, round(shock * 100)),
                round(lat * 1e6),
                round(lon * 1e6),
                hub_flags,
                self.flap,
                int(self.batt),
                self.edge_alert,
            )

        self._queue(self._emit(self.hub, build_hub))
        await self._flush()

        self.t += cfg.sample_s
        self.tick_no += 1
        return self.snapshot(row)

    # ------------------------------------------------------------------ uplink
    async def connect(self) -> None:
        await self.uplink.connect()
        self._announce = True

    async def network_cut(self) -> None:
        if self.offline_since is None:
            self.offline_since = int(self.t)
        await self.uplink.drop()
        self.note("NETWORK LOST: logging continues, records are queued")

    async def network_restore(self) -> None:
        await self.uplink.connect()
        self._announce = True
        self.note(f"NETWORK BACK: syncing {len(self.queue)} queued record(s)")

    def _status(self, *, online: bool = True) -> str:
        tier = max(self.edge_alert, self.ai_tier)
        d = {
            "type": "status",
            "online": online,
            "fw": FIRMWARE,
            "batt": int(self.batt),
            "backlog": len(self.queue),
            "ts": int(self.t),
            "led": LED[tier],
            "buzzer_latched": self.buzzer_latched,
            "flap": self.flap,
            "fan": self.fan_on,
        }
        if self.offline_since is not None:
            d["offline_since"] = self.offline_since
        return json.dumps(d)

    async def _flush(self) -> None:
        if not self.uplink.connected:
            return
        ev_topic = f"rakshak/{self.cfg.hub_id}/events"
        try:
            if self._announce:
                await self.uplink.publish(ev_topic, self._status(), 1)
                self._announce = False
            sent = 0
            while self.queue and sent < self.cfg.burst:
                topic, payload = self.queue[0]
                await self.uplink.publish(topic, payload, 1)
                self.queue.popleft()
                sent += 1
            if self.offline_since is not None and not self.queue:
                self.offline_since = None
            if sent or self.tick_no % self.cfg.status_every == 0:
                await self.uplink.publish(ev_topic, self._status(), 1)
        except UplinkDown:
            self.note("uplink failed mid-send: record stays queued")

    # ------------------------------------------------------------------ commands from the backend
    async def handle_command(self, cmd: dict) -> None:
        name, arg = cmd.get("cmd"), cmd.get("arg")
        ok = True
        if name == "FLAP_SET" and arg in (0, 25, 50, 100):
            self.floor = int(arg)
            self.flap = max(self.flap, self.floor) if self.floor else self.flap
        elif name == "FAN_ON":
            self.fan_forced = True
        elif name == "FAN_OFF":
            self.fan_forced = None  # release to the edge rule
        elif name == "ALERT_WARNING":
            self.ai_tier = 1
        elif name == "ALERT_CRITICAL":
            self.ai_tier = 2
            self.buzzer_latched = True
        elif name == "ALERT_CLEAR":
            self.ai_tier = 0
        elif name == "ACK_ALERT":
            self.buzzer_latched = False
        else:
            ok = False
        self.note(
            f"command {name} {arg if arg is not None else ''} from {cmd.get('source')}: {'ok' if ok else 'ignored'}"
        )
        if self.uplink.connected and cmd.get("id"):
            try:
                await self.uplink.publish(
                    f"rakshak/{self.cfg.hub_id}/events",
                    json.dumps({"type": "cmd_ack", "id": cmd["id"], "ok": ok}),
                    1,
                )
            except UplinkDown:
                pass

    # ------------------------------------------------------------------ injections
    def inject_heat(self, extra_c: float) -> None:
        self.phys.manual_heat_c = float(extra_c)
        self.note(f"INJECT heat +{extra_c:g} C" if extra_c else "heat removed")

    def inject_ethylene(self, units_per_h: float) -> None:
        self.phys.manual_eth_units = float(units_per_h)
        self.note(
            f"INJECT ethylene source {units_per_h:g}/h"
            if units_per_h
            else "ethylene source removed"
        )

    def inject_shock(self, g: float) -> None:
        self.phys.manual_shock_g = float(g)
        self.note(f"INJECT shock {g:g} g")

    def inject_spike(self, extra_c: float) -> None:
        self.phys.manual_spike_c = float(extra_c)

    def lid_open(self, tag_id: str | None = None) -> None:
        tag = next((t for t in self.tags if t.dev.id == tag_id), self.tags[0])
        tag.lid_open = True
        self._tag_event(tag, EventCode.LID_OPEN)
        self.note(f"INJECT lid opened on {tag.dev.id}")

    def lid_close(self, tag_id: str | None = None) -> None:
        for t in self.tags:
            if tag_id in (None, t.dev.id):
                t.lid_open = False

    def reboot_tag(self, tag_id: str | None = None) -> None:
        tag = next((t for t in self.tags if t.dev.id == tag_id), self.tags[-1])
        tag.synced, tag.boot_epoch = False, int(self.t)
        self._tag_event(tag, EventCode.BOOT, valid=False)
        self.note(f"INJECT reboot of {tag.dev.id}: clock lost until the hub syncs it")

    def ble_drop(self, tag_id: str | None = None, up: bool = False) -> None:
        for t in self.tags:
            if tag_id in (None, t.dev.id):
                t.ble_up = up
        self.note(f"BLE {'restored' if up else 'lost'} for {tag_id or 'all tags'}")

    def tamper_forge(self, device_id: str | None = None, count: int = 1) -> None:
        self._forge_next[device_id or self.tags[0].dev.id] = count

    def tamper_delete(self, device_id: str | None = None, count: int = 1) -> None:
        self._drop_next[device_id or self.tags[0].dev.id] = count

    # ------------------------------------------------------------------ status for the control API
    def snapshot(self, row: dict | None = None) -> dict:
        p = self.position()
        return {
            "t": int(self.t),
            "elapsed_min": round(self.elapsed_min, 1),
            "temperature": round(sum(t.temp for t in self.tags) / len(self.tags), 2),
            "ethylene_index": round(max(t.eth for t in self.tags), 1),
            "flap": self.flap,
            "fan": self.fan_on,
            "floor": self.floor,
            "connected": self.uplink.connected,
            "backlog": len(self.queue),
            "battery": int(self.batt),
            "led": LED[max(self.edge_alert, self.ai_tier)],
            "buzzer_latched": self.buzzer_latched,
            "lat": round(p[0], 5),
            "lon": round(p[1], 5),
            "arrived": self.arrived,
            "truth_risk": round(row["risk_true"], 1)
            if row
            else None,  # simulator ground truth (debug only)
        }
