"""Shipments, live state, timelines and custody hand-overs."""

from __future__ import annotations

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from ...db.base import utcnow
from ...db.models import (
    Device,
    EventKind,
    Handover,
    Role,
    Severity,
    Shipment,
    ShipmentStatus,
    User,
)
from ...services.custody import CustodyError, add_handover
from ...services.ingest import event_to_dict, make_event
from ...services.views import shipment_live, shipment_timeline
from ..deps import CurrentUser, Session, SettingsDep, require_roles
from ..schemas import BindRequest, HandoverCreate, HandoverOut, ShipmentCreate, ShipmentOut

router = APIRouter(prefix="/api/shipments", tags=["shipments"])
_CREATE_LOCK = asyncio.Lock()

Manager = Annotated[User, Depends(require_roles(Role.ADMIN.value, Role.FPO.value))]


async def _get(session, shipment_id: str) -> Shipment:
    s = await session.get(Shipment, shipment_id)
    if s is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown shipment")
    return s


async def _bind(session, shipment: Shipment, hub_id: str | None, tag_ids: list[str]) -> None:
    if hub_id:
        hub = await session.get(Device, hub_id)
        if hub is None or hub.kind != "hub":
            raise HTTPException(422, f"unknown hub {hub_id}")
        hub.shipment_id = shipment.id
        shipment.hub_id = hub_id
    for tag_id in tag_ids:
        tag = await session.get(Device, tag_id)
        if tag is None or tag.kind != "tag":
            raise HTTPException(422, f"unknown tag {tag_id}")
        tag.shipment_id = shipment.id
        tag.hub_id = hub_id or shipment.hub_id or tag.hub_id


@router.get("", response_model=list[ShipmentOut])
async def list_shipments(
    session: Session,
    _: CurrentUser,
    status_: Annotated[str | None, Query(alias="status")] = None,
    food_type: str | None = None,
) -> list[Shipment]:
    q = select(Shipment).order_by(Shipment.created_at.desc())
    if status_:
        q = q.where(Shipment.status == status_)
    if food_type:
        q = q.where(Shipment.food_type == food_type)
    return list((await session.execute(q)).scalars())


@router.post("", response_model=ShipmentOut, status_code=status.HTTP_201_CREATED)
async def create_shipment(
    body: ShipmentCreate, session: Session, user: Manager, request: Request
) -> Shipment:
    yy = utcnow().strftime("%y")
    data = body.model_dump(exclude={"tag_ids", "hub_id"})
    async with (
        _CREATE_LOCK
    ):  # ids are allocated as count+1: serialise, and still retry if another worker won the race
        n = (await session.execute(select(func.count()).select_from(Shipment))).scalar_one() + 1
        for _attempt in range(10):
            sid = f"RKS-{yy}-{n:06d}"
            while await session.get(Shipment, sid) is not None:
                n += 1
                sid = f"RKS-{yy}-{n:06d}"
            shipment = Shipment(id=sid, created_by=user.username, **data)
            session.add(shipment)
            try:
                await session.flush()
            except IntegrityError:
                await session.rollback()
                n += 1
                continue
            await _bind(session, shipment, body.hub_id, body.tag_ids)
            await session.commit()
            return shipment
    raise HTTPException(
        status.HTTP_503_SERVICE_UNAVAILABLE, "could not allocate a shipment id, retry"
    )


@router.get("/{shipment_id}", response_model=ShipmentOut)
async def get_shipment(shipment_id: str, session: Session, _: CurrentUser) -> Shipment:
    return await _get(session, shipment_id)


@router.get("/{shipment_id}/live")
async def live(shipment_id: str, session: Session, _: CurrentUser, request: Request) -> dict:
    shipment = await _get(session, shipment_id)
    data = await shipment_live(session, shipment)
    predictor = getattr(request.app.state, "predictor", None)
    if predictor is not None:
        data["risk"] = predictor.latest(shipment_id)
    return data


@router.get("/{shipment_id}/timeline")
async def timeline(
    shipment_id: str, session: Session, _: CurrentUser, since: int | None = None
) -> dict:
    await _get(session, shipment_id)
    return await shipment_timeline(session, shipment_id, since=since)


@router.post("/{shipment_id}/bind", response_model=ShipmentOut)
async def bind(shipment_id: str, body: BindRequest, session: Session, _: Manager) -> Shipment:
    shipment = await _get(session, shipment_id)
    await _bind(session, shipment, body.hub_id, body.tag_ids)
    await session.commit()
    return shipment


@router.post("/{shipment_id}/close", response_model=ShipmentOut)
async def close(shipment_id: str, session: Session, _: Manager, request: Request) -> Shipment:
    shipment = await _get(session, shipment_id)
    shipment.status = ShipmentStatus.DELIVERED.value
    shipment.closed_at = utcnow()
    await session.commit()
    anchor = getattr(request.app.state, "anchorer", None)
    if anchor is not None:
        await anchor.anchor_shipment(shipment_id, reason="close")
    return shipment


@router.get("/{shipment_id}/custody", response_model=list[HandoverOut])
async def custody(shipment_id: str, session: Session, _: CurrentUser) -> list[Handover]:
    await _get(session, shipment_id)
    q = select(Handover).where(Handover.shipment_id == shipment_id).order_by(Handover.id)
    return list((await session.execute(q)).scalars())


@router.post(
    "/{shipment_id}/handover", response_model=HandoverOut, status_code=status.HTTP_201_CREATED
)
async def handover(
    shipment_id: str,
    body: HandoverCreate,
    session: Session,
    user: CurrentUser,
    settings: SettingsDep,
    request: Request,
) -> Handover:
    shipment = await _get(session, shipment_id)
    try:
        h = await add_handover(
            session,
            settings,
            shipment,
            user,
            stage=body.stage,
            location=body.location,
            lat=body.lat,
            lon=body.lon,
            notes=body.notes,
        )
    except CustodyError as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from exc
    ev = make_event(
        EventKind.HANDOVER,
        Severity.INFO,
        f"Hand-over recorded: {h.stage} ({user.organisation or user.username})",
        shipment_id=shipment.id,
        data={"stage": h.stage, "handover_id": h.id},
    )
    session.add(ev)
    await session.commit()
    request.app.state.realtime.publish({"type": "event", "data": event_to_dict(ev)}, shipment.id)
    anchor = getattr(request.app.state, "anchorer", None)
    if anchor is not None:
        await anchor.anchor_handover(h.id)
        await session.refresh(h)
    return h
