"""DEMO TOOLS (off by default): tamper with stored records so the Verify page can be shown catching it.

Enabled only with ``RAKSHAK_DEMO_TOOLS=true`` and only for admins. Every change is backed up and can be
restored, so a demo can be repeated. This deliberately behaves like an attacker with database access.
"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import delete, insert, select

from rakshak.codec import compute_hash, pack_body, unpack_body

from ...db.models import Record, Role, Shipment, User
from ..deps import Session, require_roles

router = APIRouter(prefix="/api/demo", tags=["demo (tamper tools)"])
Admin = Annotated[User, Depends(require_roles(Role.ADMIN.value))]

Kind = Literal["edit_value", "edit_body", "rewrite_hash", "delete_record"]


class TamperBody(BaseModel):
    shipment_id: str
    kind: Kind = "edit_value"
    seq: int | None = None
    device_id: str | None = None


def _enabled(request: Request) -> None:
    if not request.app.state.settings.demo_tools:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "demo tools are disabled (set RAKSHAK_DEMO_TOOLS=true)"
        )


def _snapshot(r: Record) -> dict:
    return {c.name: getattr(r, c.name) for c in Record.__table__.columns}


@router.get("/status")
async def demo_status(request: Request, _: Admin) -> dict:
    backups = getattr(request.app.state, "demo_backups", {})
    return {
        "enabled": request.app.state.settings.demo_tools,
        "pending_restores": {k: len(v) for k, v in backups.items()},
    }


@router.post("/tamper")
async def tamper(body: TamperBody, session: Session, _: Admin, request: Request) -> dict:
    _enabled(request)
    if await session.get(Shipment, body.shipment_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown shipment")
    q = select(Record).where(Record.shipment_id == body.shipment_id, Record.rtype == 1)
    if body.device_id:
        q = q.where(Record.device_id == body.device_id)
    if body.seq is not None:
        q = q.where(Record.seq == body.seq)
    rows = list(
        (await session.execute(q.order_by(Record.batch_id.is_(None), Record.seq))).scalars()
    )
    if not rows:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no tag record to tamper with yet")
    target = rows[len(rows) // 4] if body.seq is None else rows[0]  # an early, already-anchored one
    backups = request.app.state.__dict__.setdefault("demo_backups", {})
    backups.setdefault(body.shipment_id, []).append(_snapshot(target))

    detail: dict
    if body.kind == "edit_value":  # "it was always cold": change what the dashboard shows
        old = target.temp_c
        target.temp_c = round((old or 0) - 6.0, 2)
        detail = {"field": "temp_c", "old": old, "new": target.temp_c}
    elif body.kind == "edit_body":  # change the signed bytes, leave the hash alone
        raw = bytearray(target.body)
        raw[43] ^= 0x01
        target.body = bytes(raw)
        detail = {"field": "body", "note": "one bit flipped in the stored record"}
    elif (
        body.kind == "rewrite_hash"
    ):  # careful attacker: edit body, columns AND the record's own hash
        rec = unpack_body(target.body)
        forged = type(rec)(**{**rec.__dict__, "temp_x100": rec.temp_x100 - 600})
        target.body = pack_body(forged)
        target.hash = compute_hash(bytes.fromhex(target.prev_hash), target.body).hex()
        target.temp_c = forged.temp_c
        detail = {"field": "body+hash", "new_temp_c": forged.temp_c}
    else:  # delete_record
        await session.execute(delete(Record).where(Record.id == target.id))
        detail = {"field": "row", "note": "record deleted"}
    await session.commit()
    request.app.state.verifier._cache.clear()
    return {
        "tampered": {"device_id": target.device_id, "seq": target.seq, "kind": body.kind, **detail},
        "next": f"GET /api/verify/{body.shipment_id} now reports TAMPERED; POST /api/demo/restore undoes it",
    }


class RestoreBody(BaseModel):
    shipment_id: str


@router.post("/restore")
async def restore(body: RestoreBody, session: Session, _: Admin, request: Request) -> dict:
    _enabled(request)
    backups = getattr(request.app.state, "demo_backups", {})
    snaps = backups.pop(body.shipment_id, [])
    for snap in reversed(snaps):  # undo in reverse order
        existing = await session.get(Record, snap["id"])
        if existing is None:
            await session.execute(insert(Record).values(**snap))
        else:
            for k, v in snap.items():
                setattr(existing, k, v)
    await session.commit()
    request.app.state.verifier._cache.clear()
    return {"restored": len(snaps)}
