"""ORM models (SQLAlchemy 2.0). Schema is versioned with Alembic (backend/alembic)."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, UTCDateTime, utcnow


class Role(StrEnum):
    ADMIN = "admin"
    FPO = "fpo"
    DRIVER = "driver"
    EXPORTER = "exporter"


class Stage(StrEnum):
    """Custody stages in order (farm to fork)."""

    FARM = "FARM"
    FPO = "FPO"
    PACKHOUSE = "PACKHOUSE"
    COLD_STORAGE = "COLD_STORAGE"
    TRANSPORT = "TRANSPORT"
    RETAIL = "RETAIL"


STAGE_ORDER = [s.value for s in Stage]


class ShipmentStatus(StrEnum):
    CREATED = "CREATED"
    IN_TRANSIT = "IN_TRANSIT"
    DELIVERED = "DELIVERED"


class Severity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class EventKind(StrEnum):
    TAMPER_BAD_HASH = "TAMPER_BAD_HASH"  # record altered
    TAMPER_CHAIN_BREAK = "TAMPER_CHAIN_BREAK"  # edit + re-hash / insertion
    TAMPER_CONFLICT = "TAMPER_CONFLICT"  # same seq redelivered with a different hash
    AUTH_FAILED = "AUTH_FAILED"  # frame failed AES-GCM authentication
    MISSING_RECORDS = "MISSING_RECORDS"  # seq gap
    GAP_FILLED = "GAP_FILLED"  # previously missing records arrived late
    UNKNOWN_DEVICE = "UNKNOWN_DEVICE"
    LID_OPEN = "LID_OPEN"
    SHOCK = "SHOCK"
    LOW_BATTERY = "LOW_BATTERY"
    ALERT_WARNING = "ALERT_WARNING"
    ALERT_CRITICAL = "ALERT_CRITICAL"
    RECOVERED = "RECOVERED"
    REROUTE = "REROUTE"
    HUB_OFFLINE = "HUB_OFFLINE"
    HUB_ONLINE = "HUB_ONLINE"
    COMMAND = "COMMAND"
    HANDOVER = "HANDOVER"
    LEDGER_ANCHORED = "LEDGER_ANCHORED"


class DeviceKind(StrEnum):
    HUB = "hub"
    TAG = "tag"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(128))
    role: Mapped[str] = mapped_column(String(16))
    full_name: Mapped[str] = mapped_column(String(128), default="")
    organisation: Mapped[str] = mapped_column(String(128), default="")
    language: Mapped[str] = mapped_column(String(8), default="en")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Device(Base):
    __tablename__ = "devices"

    id: Mapped[str] = mapped_column(String(16), primary_key=True)  # device_id as in frames
    kind: Mapped[str] = mapped_column(String(8))
    name: Mapped[str] = mapped_column(String(64), default="")
    hub_id: Mapped[str | None] = mapped_column(String(16), nullable=True)  # tags: paired hub
    shipment_id: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    key_epoch: Mapped[int] = mapped_column(Integer, default=0)
    firmware_version: Mapped[str] = mapped_column(String(32), default="")
    battery_pct: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    # Hub connectivity (reported by the hub itself via the events topic / MQTT last-will)
    online: Mapped[bool] = mapped_column(Boolean, default=False)
    backlog: Mapped[int] = mapped_column(Integer, default=0)
    offline_since: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True
    )  # device-time epoch
    # Hash-chain verifier state (hex) - what the chain must continue from
    last_seq: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    last_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Shipment(Base):
    __tablename__ = "shipments"

    id: Mapped[str] = mapped_column(String(16), primary_key=True)  # e.g. RKS-26-000418
    food_type: Mapped[str] = mapped_column(String(32))
    variety: Mapped[str] = mapped_column(String(64), default="")
    weight_kg: Mapped[float] = mapped_column(Float, default=0.0)
    grade: Mapped[str] = mapped_column(String(16), default="")
    origin_name: Mapped[str] = mapped_column(String(128), default="")
    origin_lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    origin_lon: Mapped[float | None] = mapped_column(Float, nullable=True)
    dest_name: Mapped[str] = mapped_column(String(128), default="")
    dest_lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    dest_lon: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default=ShipmentStatus.CREATED.value)
    hub_id: Mapped[str | None] = mapped_column(String(16), nullable=True)
    created_by: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    closed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    model_profile: Mapped[str] = mapped_column(String(8), default="real", server_default="real")

    handovers: Mapped[list[Handover]] = relationship(
        back_populates="shipment", order_by="Handover.id", cascade="all, delete-orphan"
    )


class Record(Base):
    """One verified, decrypted device record (sample or event)."""

    __tablename__ = "records"
    __table_args__ = (
        UniqueConstraint("device_id", "seq", name="uq_record_device_seq"),
        Index("ix_record_shipment_time", "shipment_id", "time_utc"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    device_id: Mapped[str] = mapped_column(String(16), index=True)
    shipment_id: Mapped[str] = mapped_column(String(16), index=True)
    via_hub: Mapped[str | None] = mapped_column(String(16), nullable=True)
    seq: Mapped[int] = mapped_column(BigInteger)
    rtype: Mapped[int] = mapped_column(Integer)  # 1 tag, 2 hub, 3 event
    key_epoch: Mapped[int] = mapped_column(Integer, default=0)
    ts: Mapped[int] = mapped_column(BigInteger)  # as sent by the device
    ts_valid: Mapped[bool] = mapped_column(Boolean)
    time_utc: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True
    )  # epoch; re-based if needed
    time_estimated: Mapped[bool] = mapped_column(Boolean, default=False)
    received_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    prev_hash: Mapped[str] = mapped_column(String(64))
    hash: Mapped[str] = mapped_column(String(64))
    hash_ok: Mapped[bool] = mapped_column(Boolean, default=True)
    chain_ok: Mapped[bool] = mapped_column(Boolean, default=True)
    body: Mapped[bytes] = mapped_column(LargeBinary)
    # Decoded, query-friendly columns (NULL where a record type does not carry the field)
    temp_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    rh_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    ethylene_idx: Mapped[float | None] = mapped_column(Float, nullable=True)
    shock_g: Mapped[float | None] = mapped_column(Float, nullable=True)
    lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    lon: Mapped[float | None] = mapped_column(Float, nullable=True)
    flap_pct: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fan_on: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    lid_open: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    batt_pct: Mapped[int | None] = mapped_column(Integer, nullable=True)
    alert_level: Mapped[int | None] = mapped_column(Integer, nullable=True)
    event_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    batch_id: Mapped[int | None] = mapped_column(
        ForeignKey("batches.id"), nullable=True, index=True
    )


class Batch(Base):
    """A Merkle batch of record hashes of one device within one shipment (Phase 3)."""

    __tablename__ = "batches"

    id: Mapped[int] = mapped_column(primary_key=True)
    shipment_id: Mapped[str] = mapped_column(String(16), index=True)
    device_id: Mapped[str] = mapped_column(String(16))
    first_seq: Mapped[int] = mapped_column(BigInteger)
    last_seq: Mapped[int] = mapped_column(BigInteger)
    leaf_count: Mapped[int] = mapped_column(Integer)
    merkle_root: Mapped[str] = mapped_column(String(64))
    reason: Mapped[str] = mapped_column(String(32), default="size")  # size | handover | close
    ledger_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Event(Base):
    __tablename__ = "events"
    __table_args__ = (Index("ix_event_shipment_created", "shipment_id", "created_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    shipment_id: Mapped[str | None] = mapped_column(String(16), nullable=True)
    device_id: Mapped[str | None] = mapped_column(String(16), nullable=True)
    kind: Mapped[str] = mapped_column(String(32), index=True)
    severity: Mapped[str] = mapped_column(String(10))
    message: Mapped[str] = mapped_column(String(255))
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    acknowledged_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    acknowledged_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class OfflineSegment(Base):
    """A period during which a hub had no uplink; start/end are device-time epochs."""

    __tablename__ = "offline_segments"

    id: Mapped[int] = mapped_column(primary_key=True)
    hub_id: Mapped[str] = mapped_column(String(16), index=True)
    shipment_id: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    start_ts: Mapped[int] = mapped_column(BigInteger)
    end_ts: Mapped[int | None] = mapped_column(BigInteger, nullable=True)  # NULL = still offline
    backlog_at_end: Mapped[int | None] = mapped_column(Integer, nullable=True)


class Handover(Base):
    __tablename__ = "handovers"

    id: Mapped[int] = mapped_column(primary_key=True)
    shipment_id: Mapped[str] = mapped_column(ForeignKey("shipments.id"), index=True)
    stage: Mapped[str] = mapped_column(String(16))
    actor_username: Mapped[str] = mapped_column(String(64))
    actor_name: Mapped[str] = mapped_column(String(128), default="")
    actor_role: Mapped[str] = mapped_column(String(16))
    organisation: Mapped[str] = mapped_column(String(128), default="")
    location: Mapped[str] = mapped_column(String(128), default="")
    lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    lon: Mapped[float | None] = mapped_column(Float, nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    prev_hash: Mapped[str] = mapped_column(String(64))  # chain of hand-overs per shipment
    payload_hash: Mapped[str] = mapped_column(String(64))
    public_key: Mapped[str] = mapped_column(String(64))  # Ed25519, hex
    signature: Mapped[str] = mapped_column(String(128))  # Ed25519, hex
    batch_id: Mapped[int | None] = mapped_column(ForeignKey("batches.id"), nullable=True)
    ledger_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)

    shipment: Mapped[Shipment] = relationship(back_populates="handovers")


class CommandLog(Base):
    __tablename__ = "command_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    cmd_id: Mapped[str] = mapped_column(String(36), unique=True)
    hub_id: Mapped[str] = mapped_column(String(16), index=True)
    shipment_id: Mapped[str | None] = mapped_column(String(16), nullable=True)
    cmd: Mapped[str] = mapped_column(String(24))
    arg: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source: Mapped[str] = mapped_column(String(64))  # "ai" or "user:<name>"
    status: Mapped[str] = mapped_column(String(10), default="SENT")  # SENT | ACKED | FAILED
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    acked_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class RiskPoint(Base):
    """One prediction (device time ``t``) for the risk chart and the audit trail of AI decisions."""

    __tablename__ = "risk_points"
    __table_args__ = (Index("ix_risk_shipment_t", "shipment_id", "t"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    shipment_id: Mapped[str] = mapped_column(String(16))
    t: Mapped[int] = mapped_column(BigInteger)
    risk: Mapped[float] = mapped_column(Float)
    rsl_hours: Mapped[float] = mapped_column(Float)
    level: Mapped[int] = mapped_column(Integer)
    profile: Mapped[str] = mapped_column(String(8))
    temp_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    ethylene_idx: Mapped[float | None] = mapped_column(Float, nullable=True)
