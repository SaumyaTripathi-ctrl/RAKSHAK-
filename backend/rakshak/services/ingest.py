"""Frame ingest: decrypt -> verify hash chain -> dedupe -> store -> notify.

Everything arriving from MQTT (and from tests/simulator through the same code path) goes through
:meth:`Ingestor.ingest_frame`; hub status JSON goes through :meth:`Ingestor.handle_hub_event`.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..codec import (
    ChainState,
    CodecError,
    EventCode,
    Finding,
    FindingKind,
    HubSample,
    TagSample,
    compute_hash,
    decode_frame,
    derive_device_key,
    peek_header,
    verify_next,
)
from ..codec import Event as EventRecord
from ..codec import spec as codec_spec
from ..config import Settings
from ..db.base import Database, utcnow
from ..db.models import (
    CommandLog,
    Device,
    Event,
    EventKind,
    OfflineSegment,
    Record,
    Severity,
    Shipment,
    ShipmentStatus,
)
from .realtime import RealtimeHub

log = logging.getLogger("rakshak.ingest")

LOW_BATTERY_PCT = 15


@dataclass
class IngestResult:
    status: str  # stored | late_filled | duplicate | rejected
    device_id: str | None = None
    seq: int | None = None
    shipment_id: str | None = None
    findings: list[Finding] = field(default_factory=list)
    events: list[Event] = field(default_factory=list)
    record: Record | None = None
    reason: str = ""

    @property
    def stored(self) -> bool:
        return self.status in ("stored", "late_filled")


Listener = Callable[[IngestResult], Awaitable[None]]


def record_columns(rec) -> dict:
    """Query-friendly columns derived from a decoded record body (single source of truth: ingest
    writes them, the verifier recomputes them to catch edits to displayed values)."""
    cols: dict = {}
    if isinstance(rec, TagSample):
        cols.update(
            temp_c=rec.temp_c,
            rh_pct=rec.rh_pct,
            ethylene_idx=rec.ethylene_idx,
            lid_open=rec.lid_open,
            batt_pct=rec.batt_pct,
        )
    elif isinstance(rec, HubSample):
        cols.update(
            temp_c=rec.temp_c,
            rh_pct=rec.rh_pct,
            shock_g=rec.shock_g,
            flap_pct=rec.flap_pct,
            fan_on=rec.fan_on,
            lid_open=rec.lid_open,
            batt_pct=rec.batt_pct,
            alert_level=rec.alert_level,
        )
        if rec.gps_valid:
            cols.update(lat=rec.lat, lon=rec.lon)
    else:
        cols.update(
            event_code=rec.event_code,
            batt_pct=rec.batt_pct,
            lid_open=bool(rec.flags & codec_spec.TagFlags.LID_OPEN),
        )
    return cols


COLUMN_NAMES = (
    "temp_c", "rh_pct", "ethylene_idx", "shock_g", "lat", "lon", "flap_pct",
    "fan_on", "lid_open", "batt_pct", "alert_level", "event_code",
)  # fmt: skip


def _record_to_dict(r: Record) -> dict:
    return {
        "id": r.id,
        "device_id": r.device_id,
        "shipment_id": r.shipment_id,
        "seq": r.seq,
        "rtype": r.rtype,
        "time_utc": r.time_utc,
        "time_estimated": r.time_estimated,
        "temp_c": r.temp_c,
        "rh_pct": r.rh_pct,
        "ethylene_idx": r.ethylene_idx,
        "shock_g": r.shock_g,
        "lat": r.lat,
        "lon": r.lon,
        "flap_pct": r.flap_pct,
        "fan_on": r.fan_on,
        "lid_open": r.lid_open,
        "batt_pct": r.batt_pct,
        "alert_level": r.alert_level,
        "event_code": r.event_code,
        "hash_ok": r.hash_ok,
        "chain_ok": r.chain_ok,
    }


def event_to_dict(e: Event) -> dict:
    return {
        "id": e.id,
        "shipment_id": e.shipment_id,
        "device_id": e.device_id,
        "kind": e.kind,
        "severity": e.severity,
        "message": e.message,
        "data": e.data,
        "created_at": e.created_at.isoformat(),
        "acknowledged_by": e.acknowledged_by,
        "acknowledged_at": e.acknowledged_at.isoformat() if e.acknowledged_at else None,
    }


def make_event(
    kind: EventKind,
    severity: Severity,
    message: str,
    *,
    shipment_id: str | None = None,
    device_id: str | None = None,
    data: dict | None = None,
) -> Event:
    return Event(
        kind=kind.value,
        severity=severity.value,
        message=message[:255],
        shipment_id=shipment_id,
        device_id=device_id,
        data=data or {},
        created_at=utcnow(),
    )


class Ingestor:
    def __init__(self, db: Database, settings: Settings, realtime: RealtimeHub) -> None:
        self.db = db
        self.settings = settings
        self.realtime = realtime
        self._lock = asyncio.Lock()  # one frame at a time: keeps per-device chain state consistent
        self._listeners: list[Listener] = []
        self.counters = {"stored": 0, "duplicate": 0, "rejected": 0, "late_filled": 0}

    def add_listener(self, fn: Listener) -> None:
        self._listeners.append(fn)

    # ------------------------------------------------------------------ frames
    async def ingest_frame(self, frame: bytes, via_hub: str | None = None) -> IngestResult:
        async with self._lock:
            async with self.db.session_factory() as session:
                result = await self._ingest(session, frame, via_hub)
                await session.commit()
        self.counters[result.status] = self.counters.get(result.status, 0) + 1
        self._announce(result)
        for fn in self._listeners:
            try:
                await fn(result)
            except Exception:  # listeners must never break ingest
                log.exception("ingest listener failed")
        return result

    def _announce(self, result: IngestResult) -> None:
        if result.record is not None and result.stored:
            self.realtime.publish(
                {"type": "record", "data": _record_to_dict(result.record)},
                result.record.shipment_id,
            )
        for ev in result.events:
            self.realtime.publish({"type": "event", "data": event_to_dict(ev)}, ev.shipment_id)

    async def _reject(
        self, session: AsyncSession, reason: str, event: Event | None, **kw
    ) -> IngestResult:
        events = []
        if event is not None:
            session.add(event)
            await session.flush()
            events.append(event)
        return IngestResult("rejected", reason=reason, events=events, **kw)

    async def _ingest(
        self, session: AsyncSession, frame: bytes, via_hub: str | None
    ) -> IngestResult:
        try:
            header = peek_header(frame)
        except CodecError as exc:
            log.warning("malformed frame rejected: %s", exc)
            return IngestResult("rejected", reason=f"malformed: {exc}")

        device = await session.get(Device, header.device_id)
        if device is None:
            ev = make_event(
                EventKind.UNKNOWN_DEVICE,
                Severity.WARNING,
                f"Frame from unregistered device {header.device_id}",
                device_id=header.device_id,
            )
            if not await self._recent_unacked(session, ev):
                return await self._reject(
                    session, "unknown device", ev, device_id=header.device_id, seq=header.seq
                )
            return IngestResult("rejected", reason="unknown device", device_id=header.device_id)

        if header.key_epoch > device.key_epoch:
            ev = make_event(
                EventKind.AUTH_FAILED,
                Severity.CRITICAL,
                f"{device.id}: frame uses key_epoch {header.key_epoch} > provisioned {device.key_epoch}",
                device_id=device.id,
                shipment_id=device.shipment_id,
            )
            return await self._reject(
                session, "unknown key_epoch", ev, device_id=device.id, seq=header.seq
            )

        key = derive_device_key(self.settings.master_key, device.id, header.key_epoch)
        try:
            decoded = decode_frame(frame, key)
        except CodecError as exc:
            ev = make_event(
                EventKind.AUTH_FAILED,
                Severity.CRITICAL,
                f"{device.id} seq {header.seq}: frame failed authentication (modified or wrong key)",
                device_id=device.id,
                shipment_id=device.shipment_id,
                data={"seq": header.seq, "error": str(exc)},
            )
            return await self._reject(
                session, "auth failed", ev, device_id=device.id, seq=header.seq
            )

        rec = decoded.record
        stored_hash = decoded.hash.hex()
        existing = (
            await session.execute(
                select(Record).where(Record.device_id == device.id, Record.seq == rec.seq)
            )
        ).scalar_one_or_none()
        if existing is not None:
            if existing.hash == stored_hash:
                return IngestResult("duplicate", device.id, rec.seq, rec.shipment_id)
            ev = make_event(
                EventKind.TAMPER_CONFLICT,
                Severity.CRITICAL,
                f"{device.id} seq {rec.seq} redelivered with a different hash (replay/forgery)",
                device_id=device.id,
                shipment_id=rec.shipment_id,
                data={"seq": rec.seq, "stored_hash": existing.hash, "new_hash": stored_hash},
            )
            return await self._reject(
                session, "conflicting redelivery", ev, device_id=device.id, seq=rec.seq
            )

        events: list[Event] = []
        late = device.last_seq is not None and rec.seq < device.last_seq
        if late:
            findings = await self._verify_late(session, device, decoded)
        else:
            state = ChainState(
                device.last_seq,
                bytes.fromhex(device.last_hash) if device.last_hash else codec_spec.GENESIS_HASH,
            )
            findings = verify_next(state, rec.seq, decoded.prev_hash, decoded.body, decoded.hash)
            device.last_seq, device.last_hash = state.last_seq, state.last_hash.hex()

        bad_hash = any(f.kind is FindingKind.BAD_HASH for f in findings)
        broken = any(f.is_tamper for f in findings)
        for f in findings:
            events.append(self._finding_event(f, device, rec.shipment_id))

        row = self._build_record(decoded, via_hub, bad_hash, broken)
        row.batch_id = None
        session.add(row)
        device.last_seen_at = row.received_at
        if rec.batt_pct is not None:
            device.battery_pct = rec.batt_pct
        if device.shipment_id is None:
            device.shipment_id = rec.shipment_id
        if via_hub and device.kind == "tag" and device.hub_id is None:
            device.hub_id = via_hub
        await session.flush()

        if isinstance(rec, EventRecord):
            events.extend(await self._handle_event_record(session, device, row, rec))
        elif isinstance(rec, HubSample):
            events.extend(await self._handle_hub_sample(session, device, row, rec))
        if late:
            events.append(
                make_event(
                    EventKind.GAP_FILLED,
                    Severity.INFO,
                    f"{device.id}: late record seq {rec.seq} arrived and was verified",
                    device_id=device.id,
                    shipment_id=rec.shipment_id,
                    data={"seq": rec.seq},
                )
            )

        shipment = await session.get(Shipment, rec.shipment_id)
        if shipment is not None and shipment.status == ShipmentStatus.CREATED.value:
            shipment.status = ShipmentStatus.IN_TRANSIT.value
        if shipment is not None and device.kind == "hub" and shipment.hub_id is None:
            shipment.hub_id = device.id

        for ev in events:
            session.add(ev)
        await session.flush()
        return IngestResult(
            "late_filled" if late else "stored",
            device.id,
            rec.seq,
            rec.shipment_id,
            findings,
            events,
            row,
        )

    # ------------------------------------------------------------------ helpers
    async def _recent_unacked(self, session: AsyncSession, ev: Event) -> bool:
        q = select(Event.id).where(
            Event.kind == ev.kind, Event.device_id == ev.device_id, Event.acknowledged_at.is_(None)
        )
        return (await session.execute(q.limit(1))).first() is not None

    async def _verify_late(self, session: AsyncSession, device: Device, decoded) -> list[Finding]:
        """A record below the device's high-water mark that we never stored (gap filled late)."""
        rec = decoded.record
        findings: list[Finding] = []
        if compute_hash(decoded.prev_hash, decoded.body) != decoded.hash:
            findings.append(Finding(FindingKind.BAD_HASH, rec.seq))
        prev = (
            await session.execute(
                select(Record).where(Record.device_id == device.id, Record.seq == rec.seq - 1)
            )
        ).scalar_one_or_none()
        nxt = (
            await session.execute(
                select(Record).where(Record.device_id == device.id, Record.seq == rec.seq + 1)
            )
        ).scalar_one_or_none()
        expected_prev = (
            codec_spec.GENESIS_HASH.hex() if rec.seq == 0 else (prev.hash if prev else None)
        )
        if expected_prev is not None and decoded.prev_hash.hex() != expected_prev:
            findings.append(Finding(FindingKind.CHAIN_BREAK, rec.seq))
        if nxt is not None and nxt.prev_hash != decoded.hash.hex():
            findings.append(Finding(FindingKind.CHAIN_BREAK, rec.seq + 1))
            nxt.chain_ok = False
        return findings

    def _finding_event(self, f: Finding, device: Device, shipment_id: str) -> Event:
        common = {"device_id": device.id, "shipment_id": shipment_id}
        if f.kind is FindingKind.BAD_HASH:
            return make_event(
                EventKind.TAMPER_BAD_HASH,
                Severity.CRITICAL,
                f"{device.id} seq {f.seq}: stored hash does not match record content (TAMPER)",
                data={"seq": f.seq},
                **common,
            )
        if f.kind is FindingKind.CHAIN_BREAK:
            return make_event(
                EventKind.TAMPER_CHAIN_BREAK,
                Severity.CRITICAL,
                f"{device.id} seq {f.seq}: hash chain broken (TAMPER)",
                data={"seq": f.seq},
                **common,
            )
        if f.kind is FindingKind.MISSING:
            return make_event(
                EventKind.MISSING_RECORDS,
                Severity.WARNING,
                f"{device.id}: {f.count} record(s) missing from seq {f.seq}",
                data={"first_seq": f.seq, "count": f.count},
                **common,
            )
        return make_event(  # DUPLICATE only reaches here for seqs not stored: treat as info
            EventKind.GAP_FILLED,
            Severity.INFO,
            f"{device.id} seq {f.seq} redelivered",
            data={"seq": f.seq},
            **common,
        )

    def _build_record(self, decoded, via_hub: str | None, bad_hash: bool, broken: bool) -> Record:
        rec = decoded.record
        row = Record(
            device_id=rec.device_id,
            shipment_id=rec.shipment_id,
            via_hub=via_hub,
            seq=rec.seq,
            rtype=int(rec.TYPE),
            key_epoch=decoded.header.key_epoch,
            ts=rec.ts,
            ts_valid=rec.ts_valid,
            time_utc=rec.ts if rec.ts_valid else None,
            received_at=utcnow(),
            prev_hash=decoded.prev_hash.hex(),
            hash=decoded.hash.hex(),
            hash_ok=not bad_hash,
            chain_ok=not broken,
            body=decoded.body,
        )
        for name, value in record_columns(rec).items():
            setattr(row, name, value)
        return row

    async def _handle_event_record(
        self, session: AsyncSession, device: Device, row: Record, rec: EventRecord
    ) -> list[Event]:
        out: list[Event] = []
        common = {"device_id": device.id, "shipment_id": rec.shipment_id}
        code = rec.event_code
        if code == EventCode.TIME_SYNC and rec.ts_valid:
            await self._rebase_times(session, device.id, row.seq, rec.ts - rec.arg32)
        elif code == EventCode.LID_OPEN:
            out.append(
                make_event(
                    EventKind.LID_OPEN,
                    Severity.WARNING,
                    f"{device.id}: lid opened (possible tamper)",
                    data={"seq": row.seq, "time_utc": row.time_utc},
                    **common,
                )
            )
        elif code == EventCode.SHOCK:
            out.append(
                make_event(
                    EventKind.SHOCK,
                    Severity.WARNING,
                    f"{device.id}: shock {rec.arg0 / 100:.2f} g",
                    data={"seq": row.seq, "shock_g": rec.arg0 / 100},
                    **common,
                )
            )
        elif code == EventCode.LOW_BATTERY or (
            rec.batt_pct < LOW_BATTERY_PCT and code == EventCode.BOOT
        ):
            out.append(
                make_event(
                    EventKind.LOW_BATTERY,
                    Severity.WARNING,
                    f"{device.id}: battery low ({rec.batt_pct}%)",
                    data={"batt_pct": rec.batt_pct},
                    **common,
                )
            )
        elif code == EventCode.KEY_ROTATED:
            log.info("%s reports key rotation to epoch %s", device.id, rec.arg0)
        return out

    async def _rebase_times(
        self, session: AsyncSession, device_id: str, sync_seq: int, offset: int
    ) -> None:
        """Re-base unsynced (monotonic) timestamps between the last BOOT and this TIME_SYNC."""
        boot_seq = (
            await session.execute(
                select(Record.seq)
                .where(
                    Record.device_id == device_id,
                    Record.rtype == int(codec_spec.RecordType.EVENT),
                    Record.event_code == int(EventCode.BOOT),
                    Record.seq < sync_seq,
                )
                .order_by(Record.seq.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        await session.execute(
            update(Record)
            .where(
                Record.device_id == device_id,
                Record.seq < sync_seq,
                Record.seq > (boot_seq if boot_seq is not None else -1),
                Record.ts_valid.is_(False),
            )
            .values(time_utc=Record.ts + offset, time_estimated=True)
        )

    async def _handle_hub_sample(
        self, session: AsyncSession, device: Device, row: Record, rec: HubSample
    ) -> list[Event]:
        prev_level = (
            await session.execute(
                select(Record.alert_level)
                .where(Record.device_id == device.id, Record.rtype == 2, Record.seq < row.seq)
                .order_by(Record.seq.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        prev_level = prev_level or 0
        level = rec.alert_level
        if level == prev_level:
            return []
        common = {"device_id": device.id, "shipment_id": rec.shipment_id}
        data = {"level": level, "previous": prev_level, "source": "hub", "temp_c": rec.temp_c}
        if level == 2:
            return [
                make_event(
                    EventKind.ALERT_CRITICAL,
                    Severity.CRITICAL,
                    f"{device.id}: CRITICAL (hub edge alert)",
                    data=data,
                    **common,
                )
            ]
        if level == 1 and prev_level == 0:
            return [
                make_event(
                    EventKind.ALERT_WARNING,
                    Severity.WARNING,
                    f"{device.id}: WARNING (hub edge alert)",
                    data=data,
                    **common,
                )
            ]
        if level == 0:
            return [
                make_event(
                    EventKind.RECOVERED,
                    Severity.INFO,
                    f"{device.id}: back to SAFE",
                    data=data,
                    **common,
                )
            ]
        return []

    # ------------------------------------------------------------------ hub JSON events
    async def handle_hub_event(self, hub_id: str, payload: bytes | str | dict) -> list[Event]:
        if not isinstance(payload, dict):
            try:
                payload = json.loads(payload)
            except (ValueError, TypeError):
                log.warning("hub %s sent non-JSON event", hub_id)
                return []
        if not isinstance(payload, dict):
            return []
        kind = payload.get("type")
        async with self._lock, self.db.session_factory() as session:
            device = await session.get(Device, hub_id)
            if device is None or device.kind != "hub":
                return []
            events: list[Event] = []
            if kind == "status":
                events = await self._handle_status(session, device, payload)
            elif kind == "cmd_ack":
                events = await self._handle_cmd_ack(session, device, payload)
            for ev in events:
                session.add(ev)
            await session.commit()
            status_msg = self._hub_status_dict(device)
        self.realtime.publish({"type": "hub_status", "data": status_msg}, device.shipment_id)
        for ev in events:
            self.realtime.publish({"type": "event", "data": event_to_dict(ev)}, ev.shipment_id)
        return events

    @staticmethod
    def _hub_status_dict(d: Device) -> dict:
        return {
            "device_id": d.id,
            "online": d.online,
            "backlog": d.backlog,
            "offline_since": d.offline_since,
            "battery_pct": d.battery_pct,
            "firmware_version": d.firmware_version,
            "last_seen_at": d.last_seen_at.isoformat() if d.last_seen_at else None,
            "shipment_id": d.shipment_id,
        }

    async def _handle_status(self, session: AsyncSession, device: Device, p: dict) -> list[Event]:
        now = utcnow()
        device.last_seen_at = now
        if isinstance(p.get("fw"), str):
            device.firmware_version = p["fw"][:32]
        if isinstance(p.get("batt"), int):
            device.battery_pct = max(0, min(100, p["batt"]))
        if isinstance(p.get("backlog"), int):
            device.backlog = max(0, p["backlog"])
        online = bool(p.get("online", True))
        common = {"device_id": device.id, "shipment_id": device.shipment_id}
        open_seg = (
            await session.execute(
                select(OfflineSegment)
                .where(OfflineSegment.hub_id == device.id, OfflineSegment.end_ts.is_(None))
                .order_by(OfflineSegment.id.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        events: list[Event] = []
        dev_now = p.get("ts") if isinstance(p.get("ts"), int) else int(now.timestamp())
        if online:
            since = p.get("offline_since") if isinstance(p.get("offline_since"), int) else None
            was_offline = (not device.online) or open_seg is not None or since is not None
            device.online, device.offline_since = True, None
            if open_seg is not None:
                if since is not None:
                    open_seg.start_ts = min(open_seg.start_ts, since)
                open_seg.end_ts, open_seg.backlog_at_end = dev_now, device.backlog
            elif since is not None:
                session.add(
                    OfflineSegment(
                        hub_id=device.id,
                        shipment_id=device.shipment_id,
                        start_ts=since,
                        end_ts=dev_now,
                        backlog_at_end=device.backlog,
                    )
                )
            if was_offline:
                events.append(
                    make_event(
                        EventKind.HUB_ONLINE,
                        Severity.INFO,
                        f"{device.id} back online (backlog {device.backlog} record(s) syncing)",
                        data={"backlog": device.backlog, "offline_since": since},
                        **common,
                    )
                )
        else:
            if open_seg is None:
                last_ts = (
                    await session.execute(
                        select(Record.time_utc)
                        .where(Record.device_id == device.id, Record.time_utc.is_not(None))
                        .order_by(Record.seq.desc())
                        .limit(1)
                    )
                ).scalar_one_or_none()
                start = last_ts if last_ts is not None else int(now.timestamp())
                session.add(
                    OfflineSegment(hub_id=device.id, shipment_id=device.shipment_id, start_ts=start)
                )
                device.offline_since = start
            if device.online:
                events.append(
                    make_event(
                        EventKind.HUB_OFFLINE,
                        Severity.WARNING,
                        f"{device.id} went offline (logging continues on the device)",
                        data={},
                        **common,
                    )
                )
            device.online = False
        return events

    async def _handle_cmd_ack(self, session: AsyncSession, device: Device, p: dict) -> list[Event]:
        cmd_id = p.get("id")
        log_row = (
            await session.execute(select(CommandLog).where(CommandLog.cmd_id == cmd_id))
        ).scalar_one_or_none()
        if log_row is None:
            return []
        log_row.status = "ACKED" if p.get("ok", True) else "FAILED"
        log_row.acked_at = utcnow()
        return [
            make_event(
                EventKind.COMMAND,
                Severity.INFO if p.get("ok", True) else Severity.WARNING,
                f"{device.id} {log_row.status.lower()} {log_row.cmd}{'' if log_row.arg is None else ' ' + str(log_row.arg)}",
                device_id=device.id,
                shipment_id=log_row.shipment_id,
                data={"cmd": log_row.cmd, "arg": log_row.arg, "source": log_row.source},
            )
        ]


def epoch_to_iso(ts: int | None) -> str | None:
    return None if ts is None else datetime.fromtimestamp(ts, tz=utcnow().tzinfo).isoformat()
