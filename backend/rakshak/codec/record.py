"""Record bodies: fixed-size little-endian binary layouts (spec v1)."""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass
from typing import ClassVar

from . import spec
from .spec import RecordType

_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,16}$")


class CodecError(ValueError):
    """Raised for any malformed record, frame or key material."""


def pack_id(value: str, length: int = 16) -> bytes:
    if not _ID_RE.match(value) or len(value) > length:
        raise CodecError(f"invalid identifier {value!r}")
    return value.encode("ascii").ljust(length, b"\x00")


def unpack_id(raw: bytes) -> str:
    stripped = raw.rstrip(b"\x00")
    if b"\x00" in stripped or not stripped:
        raise CodecError("identifier is not NUL-padded ASCII")
    text = stripped.decode("ascii", errors="replace")
    if not _ID_RE.match(text):
        raise CodecError(f"invalid identifier {text!r}")
    return text


@dataclass(frozen=True)
class _Common:
    device_id: str
    shipment_id: str
    seq: int
    ts: int  # epoch seconds if ts_valid else device-monotonic seconds

    TYPE: ClassVar[RecordType]
    FMT: ClassVar[str]


@dataclass(frozen=True)
class TagSample(_Common):
    temp_x100: int
    rh_x100: int
    ethylene_idx_x10: int
    flags: int
    batt_pct: int

    TYPE: ClassVar[RecordType] = RecordType.TAG_SAMPLE
    FMT: ClassVar[str] = spec.TAG_BODY_FMT

    @property
    def temp_c(self) -> float:
        return self.temp_x100 / 100

    @property
    def rh_pct(self) -> float:
        return self.rh_x100 / 100

    @property
    def ethylene_idx(self) -> float:
        return self.ethylene_idx_x10 / 10

    @property
    def lid_open(self) -> bool:
        return bool(self.flags & spec.TagFlags.LID_OPEN)

    @property
    def ts_valid(self) -> bool:
        return bool(self.flags & spec.TagFlags.TS_VALID)

    def _fields(self) -> tuple:
        return (self.temp_x100, self.rh_x100, self.ethylene_idx_x10, self.flags, self.batt_pct)


@dataclass(frozen=True)
class HubSample(_Common):
    temp_x100: int
    rh_x100: int
    shock_g_x100: int
    lat_e6: int
    lon_e6: int
    flags: int
    flap_pct: int
    batt_pct: int
    alert_level: int  # 0 SAFE, 1 WARNING, 2 CRITICAL

    TYPE: ClassVar[RecordType] = RecordType.HUB_SAMPLE
    FMT: ClassVar[str] = spec.HUB_BODY_FMT

    @property
    def temp_c(self) -> float:
        return self.temp_x100 / 100

    @property
    def rh_pct(self) -> float:
        return self.rh_x100 / 100

    @property
    def shock_g(self) -> float:
        return self.shock_g_x100 / 100

    @property
    def lat(self) -> float:
        return self.lat_e6 / 1e6

    @property
    def lon(self) -> float:
        return self.lon_e6 / 1e6

    @property
    def ts_valid(self) -> bool:
        return bool(self.flags & spec.HubFlags.TS_VALID)

    @property
    def gps_valid(self) -> bool:
        return bool(self.flags & spec.HubFlags.GPS_VALID)

    @property
    def fan_on(self) -> bool:
        return bool(self.flags & spec.HubFlags.FAN_ON)

    @property
    def lid_open(self) -> bool:
        return bool(self.flags & spec.HubFlags.LID_OPEN)

    def _fields(self) -> tuple:
        return (
            self.temp_x100,
            self.rh_x100,
            self.shock_g_x100,
            self.lat_e6,
            self.lon_e6,
            self.flags,
            self.flap_pct,
            self.batt_pct,
            self.alert_level,
        )


@dataclass(frozen=True)
class Event(_Common):
    event_code: int
    arg0: int
    arg1: int
    flags: int
    batt_pct: int

    TYPE: ClassVar[RecordType] = RecordType.EVENT
    FMT: ClassVar[str] = spec.EVENT_BODY_FMT

    @property
    def ts_valid(self) -> bool:
        return bool(self.flags & spec.TagFlags.TS_VALID)

    @property
    def arg32(self) -> int:
        return self.arg0 | (self.arg1 << 16)

    def _fields(self) -> tuple:
        return (self.event_code, self.arg0, self.arg1, self.flags, self.batt_pct)


Record = TagSample | HubSample | Event
_BY_TYPE = {cls.TYPE: cls for cls in (TagSample, HubSample, Event)}


def pack_body(rec: Record) -> bytes:
    try:
        raw = struct.pack(
            rec.FMT,
            spec.VERSION,
            int(rec.TYPE),
            pack_id(rec.device_id),
            pack_id(rec.shipment_id),
            rec.seq,
            rec.ts,
            *rec._fields(),
        )
    except struct.error as exc:  # out-of-range field
        raise CodecError(f"field out of range: {exc}") from exc
    assert len(raw) == spec.BODY_LEN[rec.TYPE]
    return raw


def unpack_body(raw: bytes) -> Record:
    if len(raw) < spec.COMMON_LEN:
        raise CodecError("body too short")
    version, rtype = raw[0], raw[1]
    if version != spec.VERSION:
        raise CodecError(f"unsupported version {version}")
    try:
        cls = _BY_TYPE[RecordType(rtype)]
    except ValueError as exc:
        raise CodecError(f"unknown record type {rtype}") from exc
    if len(raw) != spec.BODY_LEN[cls.TYPE]:
        raise CodecError(f"bad body length {len(raw)} for type {rtype}")
    _, _, dev, shp, seq, ts, *rest = struct.unpack(cls.FMT, raw)
    return cls(unpack_id(dev), unpack_id(shp), seq, ts, *rest)
