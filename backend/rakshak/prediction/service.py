"""Live spoilage prediction, alert state machine, AI commands and rerouting.

Flow for every stored sample: update the per-shipment tracker -> (on each hub sample) build one crate reading from
the latest tag values -> FeatureEngine -> Random Forest pair -> risk + remaining safe life -> alert state machine
(SAFE/WARNING/CRITICAL, 15 s recovery hold, latching alarm) -> events, realtime push, AI commands to the hub
(``FLAP_SET`` floor, ``FAN_ON/OFF``, ``ALERT_*``) and, on entering CRITICAL, a reroute recommendation.

Models are trained on SIMULATED data (see ml/MODEL_CARD.md); every prediction carries its model profile.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from pathlib import Path

from rakshak_ml.alert import AlertStateMachine, Level
from rakshak_ml.bands import FoodBand, get_band
from rakshak_ml.features import FeatureEngine, Reading
from rakshak_ml.model import ModelBundle, ModelNotFoundError
from rakshak_ml.train import DEFAULT_OUT
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import Settings
from ..db.base import Database, utcnow
from ..db.models import (
    Device,
    Event,
    EventKind,
    Record,
    RiskPoint,
    Severity,
    Shipment,
    ShipmentStatus,
)
from ..services.commands import CommandError, send_command
from ..services.ingest import IngestResult, event_to_dict, make_event
from ..services.realtime import RealtimeHub
from .explain import drivers
from .facilities import Facility
from .reroute import RerouteRecommendation, recommend
from .routing import Router
from .weather import WeatherClient

log = logging.getLogger("rakshak.prediction")

TAG_FRESH_S = (
    15 * 60
)  # a tag reading older than this (device time) is not part of the crate reading
RISK_MIN_INTERVAL_S = (
    55  # persist at most one risk point per minute of device time (plus level changes)
)
FLOOR_FOR_LEVEL = {Level.SAFE: 0, Level.WARNING: 50, Level.CRITICAL: 100}
ALERT_CMD = {
    Level.SAFE: "ALERT_CLEAR",
    Level.WARNING: "ALERT_WARNING",
    Level.CRITICAL: "ALERT_CRITICAL",
}


def resolve_model_dir(settings: Settings) -> Path:
    return Path(settings.model_dir) if settings.model_dir else DEFAULT_OUT / "models"


class ModelRegistry:
    def __init__(self, models_dir: Path) -> None:
        self.dir = models_dir
        self._bundles: dict[str, ModelBundle | None] = {}

    def get(self, profile: str) -> ModelBundle | None:
        if profile not in self._bundles:
            try:
                self._bundles[profile] = ModelBundle.load(self.dir, profile)
                log.info("loaded '%s' model pair from %s", profile, self.dir)
            except ModelNotFoundError as exc:
                log.warning("%s", exc)
                self._bundles[profile] = None
        return self._bundles[profile]

    def loaded_profiles(self) -> list[str]:
        return [p for p in ("real", "demo") if self.get(p) is not None]


@dataclass
class TagLast:
    t: int
    temp: float
    rh: float
    eth: float


@dataclass
class HubLast:
    t: int
    flap: int = 0
    fan: bool = False
    shock: float = 0.0
    amb_temp: float | None = None
    amb_rh: float | None = None
    lat: float | None = None
    lon: float | None = None


@dataclass
class Tracker:
    shipment_id: str
    band: FoodBand
    profile: str
    engine: FeatureEngine
    machine: AlertStateMachine
    tags: dict[str, TagLast] = field(default_factory=dict)
    hub: HubLast | None = None
    t_max: int = 0
    last_persist_t: int | None = None
    latest: dict | None = None
    floor_sent: int = 0
    fan_forced: bool = False
    reroute: dict | None = None
    reroute_accepted: str | None = None
    reroute_pending: bool = False
    reroute_announced: bool = False  # the 'Reroute recommended' event was raised for this shipment
    weather_lat: float | None = None


def rec_time(r: Record) -> int:
    return r.time_utc if r.time_utc is not None else int(r.received_at.timestamp())


class PredictionService:
    def __init__(
        self,
        app,
        db: Database,
        settings: Settings,
        realtime: RealtimeHub,
        registry: ModelRegistry,
        router: Router,
        weather: WeatherClient,
        facilities: list[Facility],
    ) -> None:
        self.app, self.db, self.settings, self.realtime = app, db, settings, realtime
        self.registry, self.router, self.weather, self.facilities = (
            registry,
            router,
            weather,
            facilities,
        )
        self.trackers: dict[str, Tracker] = {}
        self._tasks: set[asyncio.Task] = set()

    # ------------------------------------------------------------------ public
    def latest(self, shipment_id: str) -> dict | None:
        tr = self.trackers.get(shipment_id)
        return tr.latest if tr else None

    def reroute_state(self, shipment_id: str) -> dict | None:
        tr = self.trackers.get(shipment_id)
        return (
            None
            if tr is None
            else (
                {**tr.reroute, "accepted_facility_id": tr.reroute_accepted} if tr.reroute else None
            )
        )

    async def wait_idle(self) -> None:
        """Wait for background work (reroute lookups). Used by tests and graceful shutdown."""
        while self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)

    async def aclose(self) -> None:
        await self.wait_idle()
        await self.router.aclose()
        await self.weather.aclose()

    # ------------------------------------------------------------------ ingest listener
    async def on_ingest(self, result: IngestResult) -> None:
        if not result.stored or result.record is None or result.record.rtype not in (1, 2):
            return
        rec = result.record
        async with self.db.session_factory() as s:
            shipment = await s.get(Shipment, rec.shipment_id)
            if shipment is None or shipment.status == ShipmentStatus.DELIVERED.value:
                return
            tr = self.trackers.get(shipment.id) or await self._new_tracker(s, shipment, rec.id)
            if tr is None:
                return
            self._apply(tr, rec)
            if (
                rec.rtype == 2 or tr.hub is None
            ):  # hub cadence drives evaluation; tag-only shipments use tags
                await self._evaluate(s, tr, shipment, rec_time(rec), live=True)

    # ------------------------------------------------------------------ internals
    async def _new_tracker(
        self, s: AsyncSession, shipment: Shipment, current_id: int
    ) -> Tracker | None:
        try:
            band = get_band(shipment.food_type)
        except KeyError:
            log.warning(
                "shipment %s has unknown food type %r: no predictions",
                shipment.id,
                shipment.food_type,
            )
            return None
        profile = shipment.model_profile or "real"
        if self.registry.get(profile) is None:
            return None
        tr = Tracker(
            shipment.id,
            band,
            profile,
            FeatureEngine(band),
            AlertStateMachine(self.settings.recovery_hold_s),
        )
        self.trackers[shipment.id] = tr
        rows = list(
            (
                await s.execute(
                    select(Record).where(
                        Record.shipment_id == shipment.id,
                        Record.rtype.in_((1, 2)),
                        Record.hash_ok.is_(True),
                        Record.id != current_id,
                    )
                )
            ).scalars()
        )
        rows.sort(key=rec_time)
        # Rebuild state silently after a restart: no events, commands or persisted points.
        for r in rows:
            self._apply(tr, r)
            if r.rtype == 2:
                await self._evaluate(s, tr, shipment, rec_time(r), live=False)
        return tr

    @staticmethod
    def _apply(tr: Tracker, r: Record) -> None:
        t = rec_time(r)
        if r.rtype == 1 and r.temp_c is not None:
            tr.tags[r.device_id] = TagLast(t, r.temp_c, r.rh_pct or 0.0, r.ethylene_idx or 0.0)
        elif r.rtype == 2:
            prev = tr.hub
            tr.hub = HubLast(
                t,
                r.flap_pct or 0,
                bool(r.fan_on),
                r.shock_g or 0.0,
                r.temp_c,
                r.rh_pct,
                r.lat if r.lat is not None else (prev.lat if prev else None),
                r.lon if r.lon is not None else (prev.lon if prev else None),
            )

    def _crate_reading(self, tr: Tracker, t: int) -> Reading | None:
        fresh = [x for x in tr.tags.values() if t - x.t <= TAG_FRESH_S]
        if not fresh:
            return None
        temp = sum(x.temp for x in fresh) / len(fresh)
        rh = sum(x.rh for x in fresh) / len(fresh)
        eth = max(x.eth for x in fresh)
        hub = tr.hub
        w = self.weather.peek(hub.lat if hub else None, hub.lon if hub else None)
        return Reading(
            t=float(t),
            temperature=temp,
            humidity=rh,
            ethylene_index=eth,
            shock_g=hub.shock if hub else 0.0,
            external_temperature=(hub.amb_temp if hub and hub.amb_temp is not None else temp),
            external_humidity=(hub.amb_rh if hub and hub.amb_rh is not None else rh),
            rain_probability=w.rain_probability,
            wind_speed=w.wind_speed,
            flap_position=hub.flap if hub else 0,
            scrubber_on=int(hub.fan) if hub else 0,
        )

    async def _evaluate(
        self, s: AsyncSession, tr: Tracker, shipment: Shipment, t: int, *, live: bool
    ) -> None:
        reading = self._crate_reading(tr, t)
        bundle = self.registry.get(tr.profile)
        if reading is None or bundle is None:
            return
        feats = tr.engine.update(reading)
        pred = bundle.predict(feats)
        transition = tr.machine.update(pred.risk, float(t))
        if transition is not None and transition.previous is Level.CRITICAL > transition.current:
            tr.reroute, tr.reroute_accepted = (
                None,
                None,
            )  # emergency over: the next one gets a fresh detour
        level = tr.machine.level
        tr.t_max = max(tr.t_max, t)
        why = drivers(feats, tr.band)
        tr.latest = {
            "shipment_id": tr.shipment_id,
            "risk": round(pred.risk, 1),
            "level": level.name,
            "level_code": int(level),
            "rsl_hours": round(pred.rsl_hours, 1),
            "t": t,
            "model_profile": tr.profile,
            "model_note": "trained on simulated data",
            "latched": tr.machine.latched,
            "drivers": why,
            "temperature": round(reading.temperature, 2),
            "ethylene_index": round(reading.ethylene_index, 1),
            "reroute": self._reroute_summary(tr),
        }
        if not live:
            return

        if (
            tr.last_persist_t is None
            or t - tr.last_persist_t >= RISK_MIN_INTERVAL_S
            or transition is not None
        ):
            s.add(
                RiskPoint(
                    shipment_id=tr.shipment_id, t=t, risk=pred.risk, rsl_hours=pred.rsl_hours, level=int(level),
                    profile=tr.profile, temp_c=reading.temperature, ethylene_idx=reading.ethylene_index,
                )
            )  # fmt: skip
            tr.last_persist_t = t

        events: list[Event] = []
        hub_dev = await s.get(Device, shipment.hub_id) if shipment.hub_id else None
        historical = bool(hub_dev and hub_dev.backlog > 0)
        if transition is not None:
            events.append(self._transition_event(tr, transition, pred, why, t, historical))
        for ev in events:
            s.add(ev)
        await s.commit()
        self.realtime.publish({"type": "risk", "data": tr.latest}, tr.shipment_id)
        for ev in events:
            self.realtime.publish({"type": "event", "data": event_to_dict(ev)}, tr.shipment_id)

        if not historical:
            await self._steer(s, tr, shipment, level, feats, transition is not None)
            if level is Level.CRITICAL and not tr.reroute_announced and not tr.reroute_pending:
                # also covers CRITICAL reached while the hub was offline (that transition was historical)
                tr.reroute_pending = True
                self._spawn(self._auto_reroute(tr.shipment_id, pred.rsl_hours))

    def _transition_event(self, tr: Tracker, t, pred, why, at: int, historical: bool) -> Event:
        data = {
            "source": "ai",
            "risk": round(pred.risk, 1),
            "rsl_hours": round(pred.rsl_hours, 1),
            "level": t.current.name,
            "previous": t.previous.name,
            "drivers": [d["text"] for d in why[:3]],
            "time_utc": at,
            "historical": historical,
            "model_profile": tr.profile,
        }
        head = f"{tr.shipment_id}: risk {pred.risk:.0f} ({pred.rsl_hours:.0f} h safe life left)"
        common = dict(shipment_id=tr.shipment_id, data=data)
        if t.current is Level.CRITICAL:
            return make_event(
                EventKind.ALERT_CRITICAL, Severity.CRITICAL, f"CRITICAL - {head}", **common
            )
        if t.current is Level.WARNING and t.escalated:
            return make_event(
                EventKind.ALERT_WARNING, Severity.WARNING, f"WARNING - {head}", **common
            )
        msg = "back to SAFE" if t.current is Level.SAFE else f"eased to {t.current.name}"
        return make_event(EventKind.RECOVERED, Severity.INFO, f"{msg} - {head}", **common)

    async def _steer(
        self, s: AsyncSession, tr: Tracker, shipment: Shipment, level: Level, feats, changed: bool
    ) -> None:
        """AI commands to the hub. Semantics: FLAP_SET n is a *floor* (edge rules may open further, never below
        it until FLAP_SET 0); FAN_ON forces the scrubber, FAN_OFF releases it back to the edge rule."""
        if not (self.settings.ai_commands_enabled and shipment.hub_id):
            return
        want_floor = FLOOR_FOR_LEVEL[level]
        want_fan = bool(
            tr.band.ethylene_sensitive and level >= Level.WARNING and feats["ethylene_index"] >= 30
        )
        sends: list[tuple[str, int | None]] = []
        if want_floor != tr.floor_sent:
            sends.append(("FLAP_SET", want_floor))
        if want_fan != tr.fan_forced:
            sends.append(("FAN_ON" if want_fan else "FAN_OFF", None))
        if changed:
            sends.append((ALERT_CMD[level], None))
        for cmd, arg in sends:
            try:
                await send_command(
                    s,
                    self.app.state.publisher,
                    shipment.hub_id,
                    cmd,
                    arg,
                    source="ai",
                    shipment_id=shipment.id,
                )
            except CommandError as exc:
                log.warning("AI command %s rejected: %s", cmd, exc)
                continue
            if cmd == "FLAP_SET":
                tr.floor_sent = arg or 0
            elif cmd in ("FAN_ON", "FAN_OFF"):
                tr.fan_forced = cmd == "FAN_ON"
        if sends:
            await s.commit()

    # ------------------------------------------------------------------ alarm acknowledgement
    async def on_event_ack(self, ev: Event) -> None:
        if ev.kind != EventKind.ALERT_CRITICAL.value or not ev.shipment_id:
            return
        tr = self.trackers.get(ev.shipment_id)
        if tr is None or not tr.machine.acknowledge():
            return
        if tr.latest:
            tr.latest["latched"] = False
            self.realtime.publish({"type": "risk", "data": tr.latest}, tr.shipment_id)
        if self.settings.ai_commands_enabled:
            async with self.db.session_factory() as s:
                shipment = await s.get(Shipment, ev.shipment_id)
                if shipment and shipment.hub_id:
                    try:
                        await send_command(
                            s, self.app.state.publisher, shipment.hub_id, "ACK_ALERT", None,
                            source=f"user:{ev.acknowledged_by or 'operator'}", shipment_id=shipment.id,
                        )  # fmt: skip
                        await s.commit()
                    except CommandError:
                        pass

    # ------------------------------------------------------------------ rerouting
    def _spawn(self, coro) -> None:
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    @staticmethod
    def _reroute_summary(tr: Tracker) -> dict | None:
        if not tr.reroute or not tr.reroute.get("recommended"):
            return None
        rec = tr.reroute["recommended"]
        return {
            "facility": rec["facility"]["name"],
            "facility_id": rec["facility"]["id"],
            "distance_km": rec["distance_km"],
            "duration_min": rec["duration_min"],
            "accepted": tr.reroute_accepted == rec["facility"]["id"],
        }

    async def compute_reroute(
        self, shipment_id: str, *, persist_event: bool = False
    ) -> dict | None:
        tr = self.trackers.get(shipment_id)
        async with self.db.session_factory() as s:
            shipment = await s.get(Shipment, shipment_id)
            if shipment is None:
                return None
            band = tr.band if tr else get_band(shipment.food_type)
            hub = tr.hub if tr else None
            if hub and hub.lat is not None:
                origin = (hub.lat, hub.lon)
            elif shipment.origin_lat is not None:
                origin = (shipment.origin_lat, shipment.origin_lon)
            else:
                return None
            rsl = tr.latest["rsl_hours"] if tr and tr.latest else None
            rec: RerouteRecommendation = await recommend(
                self.router, self.facilities, band, origin,
                weight_kg=shipment.weight_kg, rsl_hours=rsl,
            )  # fmt: skip
            doc = {
                **rec.to_dict(),
                "computed_at": int(utcnow().timestamp()),
                "shipment_id": shipment_id,
            }
            if tr is not None:
                tr.reroute = doc
            if persist_event and rec.recommended:
                if tr is not None:
                    tr.reroute_announced = True
                best = rec.recommended
                ev = make_event(
                    EventKind.REROUTE,
                    Severity.WARNING,
                    f"Reroute recommended: {best.facility.name} - {best.distance_km:g} km, {best.duration_min:.0f} min"
                    f" ({best.routing_source})",
                    shipment_id=shipment_id,
                    data={"facility_id": best.facility.id, "distance_km": best.distance_km,
                          "duration_min": best.duration_min, "routing_source": best.routing_source},
                )  # fmt: skip
                s.add(ev)
                await s.commit()
                self.realtime.publish({"type": "event", "data": event_to_dict(ev)}, shipment_id)
            if tr is not None and tr.latest:
                tr.latest["reroute"] = self._reroute_summary(tr)
                self.realtime.publish({"type": "risk", "data": tr.latest}, shipment_id)
            self.realtime.publish({"type": "reroute", "data": doc}, shipment_id)
            return doc

    async def _auto_reroute(self, shipment_id: str, rsl_hours: float) -> None:
        try:
            await self.compute_reroute(shipment_id, persist_event=True)
        except Exception:
            log.exception("reroute computation failed for %s", shipment_id)
        finally:
            tr = self.trackers.get(shipment_id)
            if tr is not None:
                tr.reroute_pending = False

    async def accept_reroute(
        self, shipment_id: str, facility_id: str, username: str
    ) -> dict | None:
        tr = self.trackers.get(shipment_id)
        doc = tr.reroute if tr else None
        if doc is None:
            return None
        options = [doc["recommended"], *doc["alternatives"]]
        chosen = next((o for o in options if o and o["facility"]["id"] == facility_id), None)
        if chosen is None:
            return None
        tr.reroute_accepted = facility_id
        async with self.db.session_factory() as s:
            ev = make_event(
                EventKind.REROUTE,
                Severity.INFO,
                f"{username} accepted the detour to {chosen['facility']['name']}",
                shipment_id=shipment_id,
                data={
                    "facility_id": facility_id,
                    "accepted_by": username,
                    "eta_min": chosen["duration_min"],
                },
            )
            s.add(ev)
            await s.commit()
            self.realtime.publish({"type": "event", "data": event_to_dict(ev)}, shipment_id)
        if tr.latest:
            tr.latest["reroute"] = self._reroute_summary(tr)
            self.realtime.publish({"type": "risk", "data": tr.latest}, shipment_id)
        return chosen
