"""Custody hand-overs: Farm -> FPO -> Pack-house -> Cold storage -> Transport -> Retail.

Each hand-over is hash-chained per shipment (``prev_hash`` -> ``payload_hash``) and signed with the
acting user's Ed25519 key. Ledger anchoring is layered on top (``ledger`` package).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..codec import spec as codec_spec
from ..config import Settings
from ..db.base import utcnow
from ..db.models import STAGE_ORDER, Handover, Role, Shipment, User
from ..security import actor_private_key, public_key_hex, verify_signature

ROLE_STAGES: dict[str, set[str]] = {
    Role.ADMIN.value: set(STAGE_ORDER),
    Role.FPO.value: {"FARM", "FPO", "PACKHOUSE", "COLD_STORAGE"},
    Role.DRIVER.value: {"TRANSPORT", "COLD_STORAGE"},
    Role.EXPORTER.value: {"COLD_STORAGE", "RETAIL"},
}


class CustodyError(ValueError):
    pass


def canonical_payload(h: Handover | dict) -> bytes:
    get = h.get if isinstance(h, dict) else lambda k: getattr(h, k)
    created = get("created_at")
    doc = {
        "shipment_id": get("shipment_id"),
        "stage": get("stage"),
        "actor": get("actor_username"),
        "role": get("actor_role"),
        "organisation": get("organisation"),
        "location": get("location"),
        "lat": get("lat"),
        "lon": get("lon"),
        "notes": get("notes"),
        "ts": created.isoformat(timespec="microseconds"),
        "prev_hash": get("prev_hash"),
    }
    return json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )


async def add_handover(
    session: AsyncSession,
    settings: Settings,
    shipment: Shipment,
    user: User,
    *,
    stage: str,
    location: str = "",
    lat: float | None = None,
    lon: float | None = None,
    notes: str = "",
) -> Handover:
    if stage not in STAGE_ORDER:
        raise CustodyError(f"unknown stage {stage!r}; expected one of {STAGE_ORDER}")
    if stage not in ROLE_STAGES.get(user.role, set()):
        raise CustodyError(f"role {user.role!r} may not record a {stage} hand-over")
    last = (
        await session.execute(
            select(Handover)
            .where(Handover.shipment_id == shipment.id)
            .order_by(Handover.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    h = Handover(
        shipment_id=shipment.id,
        stage=stage,
        actor_username=user.username,
        actor_name=user.full_name,
        actor_role=user.role,
        organisation=user.organisation,
        location=location,
        lat=lat,
        lon=lon,
        notes=notes,
        created_at=utcnow(),
        prev_hash=last.payload_hash if last else codec_spec.GENESIS_HASH.hex(),
    )
    payload = canonical_payload(h)
    h.payload_hash = hashlib.sha256(payload).hexdigest()
    key = actor_private_key(settings.master_key, user.username)
    h.public_key = public_key_hex(key)
    h.signature = key.sign(bytes.fromhex(h.payload_hash)).hex()
    session.add(h)
    await session.flush()
    return h


@dataclass
class HandoverCheck:
    id: int
    stage: str
    ok: bool
    reason: str = ""


def verify_handovers(handovers: list[Handover]) -> list[HandoverCheck]:
    """Recompute hashes, chain links and signatures for a shipment's hand-overs (in id order)."""
    out: list[HandoverCheck] = []
    prev = codec_spec.GENESIS_HASH.hex()
    for h in handovers:
        reason = ""
        if h.prev_hash != prev:
            reason = "chain link broken (hand-over removed or reordered)"
        elif hashlib.sha256(canonical_payload(h)).hexdigest() != h.payload_hash:
            reason = "content does not match its hash (edited)"
        elif not verify_signature(h.public_key, bytes.fromhex(h.payload_hash), h.signature):
            reason = "signature invalid"
        out.append(HandoverCheck(h.id, h.stage, not reason, reason))
        prev = h.payload_hash
    return out
