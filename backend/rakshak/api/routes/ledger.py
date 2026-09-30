"""Ledger status, verification and proofs."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from ...db.models import Role, Shipment, User
from ..deps import CurrentUser, Session, require_roles

router = APIRouter(tags=["ledger"])
Manager = Annotated[User, Depends(require_roles(Role.ADMIN.value, Role.FPO.value))]


def _entry(e) -> dict:
    return {
        "ref": e.ref,
        "kind": e.kind,
        "payload": e.payload,
        "ts": e.ts,
        "prev_hash": e.prev_hash,
        "hash": e.hash,
    }


@router.get("/api/verify/{shipment_id}")
async def verify_shipment(
    shipment_id: str, session: Session, _: CurrentUser, request: Request
) -> dict:
    """Recompute every hash chain, Merkle root and hand-over signature from the database and compare
    with the ledger. ``status`` is VERIFIED | PARTIAL | PENDING | TAMPERED | LEDGER_UNREACHABLE."""
    if await session.get(Shipment, shipment_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown shipment")
    return await request.app.state.verifier.verify_shipment(session, shipment_id)


@router.post("/api/shipments/{shipment_id}/anchor")
async def anchor_now(shipment_id: str, session: Session, _: Manager, request: Request) -> dict:
    if await session.get(Shipment, shipment_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown shipment")
    batches = await request.app.state.anchorer.anchor_shipment(shipment_id, reason="manual")
    return {"anchored_batches": len(batches), "batch_ids": [b.id for b in batches]}


@router.get("/api/ledger/status")
async def ledger_status(_: CurrentUser, request: Request) -> dict:
    ledger = request.app.state.ledger
    integ = await ledger.integrity()
    return {
        "backend": ledger.name,
        "decentralised": ledger.decentralised,
        "integrity_ok": integ.ok,
        "entries": integ.entries,
        "problem": integ.problem,
    }


@router.get("/api/ledger/entries")
async def ledger_entries(
    _: CurrentUser,
    request: Request,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    shipment_id: str | None = None,
) -> list[dict]:
    entries = await request.app.state.ledger.list(
        limit=limit if not shipment_id else 500, offset=offset
    )
    if shipment_id:
        entries = [e for e in entries if e.payload.get("shipment_id") == shipment_id][:limit]
    return [_entry(e) for e in entries]


@router.get("/api/ledger/proof/{device_id}/{seq}")
async def proof(
    device_id: str, seq: int, session: Session, _: CurrentUser, request: Request
) -> dict:
    p = await request.app.state.verifier.proof(session, device_id, seq)
    if p is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "record not found or not anchored yet")
    return p
