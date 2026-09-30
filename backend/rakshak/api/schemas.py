"""Request/response models (Pydantic v2)."""

from __future__ import annotations

import re
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,16}$")


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class LoginRequest(BaseModel):
    username: str
    password: str


class UserOut(ORM):
    username: str
    role: str
    full_name: str
    organisation: str
    language: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class ShipmentCreate(BaseModel):
    food_type: str = Field(min_length=1, max_length=32)
    variety: str = ""
    weight_kg: float = Field(default=0, ge=0)
    grade: str = ""
    origin_name: str = ""
    origin_lat: float | None = Field(default=None, ge=-90, le=90)
    origin_lon: float | None = Field(default=None, ge=-180, le=180)
    dest_name: str = ""
    dest_lat: float | None = Field(default=None, ge=-90, le=90)
    dest_lon: float | None = Field(default=None, ge=-180, le=180)
    hub_id: str | None = None
    tag_ids: list[str] = Field(default_factory=list)


class ShipmentOut(ORM):
    id: str
    food_type: str
    variety: str
    weight_kg: float
    grade: str
    origin_name: str
    origin_lat: float | None
    origin_lon: float | None
    dest_name: str
    dest_lat: float | None
    dest_lon: float | None
    status: str
    hub_id: str | None
    created_by: str
    created_at: datetime
    closed_at: datetime | None


class BindRequest(BaseModel):
    hub_id: str | None = None
    tag_ids: list[str] = Field(default_factory=list)


class DeviceCreate(BaseModel):
    id: str
    kind: str = Field(pattern="^(hub|tag)$")
    name: str = ""
    hub_id: str | None = None

    @field_validator("id")
    @classmethod
    def _id(cls, v: str) -> str:
        if not ID_PATTERN.match(v):
            raise ValueError("id must be 1-16 chars of [A-Za-z0-9_-]")
        return v


class DeviceOut(ORM):
    id: str
    kind: str
    name: str
    hub_id: str | None
    shipment_id: str | None
    key_epoch: int
    firmware_version: str
    battery_pct: int | None
    last_seen_at: datetime | None
    online: bool
    backlog: int
    offline_since: int | None
    last_seq: int | None


class ProvisioningOut(BaseModel):
    device: DeviceOut
    key_epoch: int
    device_key_hex: str
    note: str = "Shown once to an admin. Write to the device NVS before enabling flash encryption."


class EventOut(ORM):
    id: int
    shipment_id: str | None
    device_id: str | None
    kind: str
    severity: str
    message: str
    data: dict
    created_at: datetime
    acknowledged_by: str | None
    acknowledged_at: datetime | None


class CommandRequest(BaseModel):
    cmd: str
    arg: int | None = None
    shipment_id: str | None = None


class CommandOut(ORM):
    cmd_id: str
    hub_id: str
    shipment_id: str | None
    cmd: str
    arg: int | None
    source: str
    status: str
    created_at: datetime


class HandoverCreate(BaseModel):
    stage: str
    location: str = ""
    lat: float | None = Field(default=None, ge=-90, le=90)
    lon: float | None = Field(default=None, ge=-180, le=180)
    notes: str = Field(default="", max_length=1000)


class HandoverOut(ORM):
    id: int
    shipment_id: str
    stage: str
    actor_username: str
    actor_name: str
    actor_role: str
    organisation: str
    location: str
    lat: float | None
    lon: float | None
    notes: str
    created_at: datetime
    prev_hash: str
    payload_hash: str
    public_key: str
    signature: str
    batch_id: int | None
    ledger_ref: str | None
