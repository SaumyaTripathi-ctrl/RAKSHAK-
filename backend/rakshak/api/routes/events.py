"""Events/alerts feed and acknowledgement, fleet overview, websocket."""

from __future__ import annotations

import asyncio
import contextlib
from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    Request,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from sqlalchemy import func, select

from ...db.base import utcnow
from ...db.models import Device, Event, Role, Shipment, ShipmentStatus, User
from ...services.ingest import event_to_dict
from ..deps import CurrentUser, Session, require_roles, user_from_token
from ..schemas import EventOut

router = APIRouter(tags=["events"])

Responder = Annotated[
    User, Depends(require_roles(Role.ADMIN.value, Role.FPO.value, Role.DRIVER.value))
]


@router.get("/api/events", response_model=list[EventOut])
async def list_events(
    session: Session,
    _: CurrentUser,
    shipment_id: str | None = None,
    severity: str | None = None,
    kind: str | None = None,
    unacked: bool = False,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[Event]:
    q = select(Event).order_by(Event.id.desc()).limit(limit)
    if shipment_id:
        q = q.where(Event.shipment_id == shipment_id)
    if severity:
        q = q.where(Event.severity == severity)
    if kind:
        q = q.where(Event.kind == kind)
    if unacked:
        q = q.where(Event.acknowledged_at.is_(None))
    return list((await session.execute(q)).scalars())


@router.post("/api/events/{event_id}/ack", response_model=EventOut)
async def ack_event(event_id: int, session: Session, user: Responder, request: Request) -> Event:
    ev = await session.get(Event, event_id)
    if ev is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown event")
    if ev.acknowledged_at is None:
        ev.acknowledged_by, ev.acknowledged_at = user.username, utcnow()
        await session.commit()
        request.app.state.realtime.publish(
            {"type": "event", "data": event_to_dict(ev)}, ev.shipment_id
        )
        predictor = getattr(request.app.state, "predictor", None)
        if predictor is not None:
            await predictor.on_event_ack(
                ev
            )  # silences the latched alarm and tells the hub (ACK_ALERT)
    return ev


@router.get("/api/fleet/overview", tags=["fleet"])
async def fleet_overview(session: Session, _: CurrentUser, request: Request) -> dict:
    """KPI tiles + one row per active shipment for the fleet map."""
    from ...services.views import shipment_live

    active = list(
        (
            await session.execute(
                select(Shipment)
                .where(Shipment.status != ShipmentStatus.DELIVERED.value)
                .order_by(Shipment.id)
            )
        ).scalars()
    )
    predictor = getattr(request.app.state, "predictor", None)
    verifier = getattr(request.app.state, "verifier", None)
    trucks = []
    at_risk = 0
    for s in active:
        live = await shipment_live(session, s)
        hub = live["hub"] or {}
        risk = predictor.latest(s.id) if predictor else None
        level = hub.get("alert_level") or 0
        if risk:
            level = max(level, {"SAFE": 0, "WARNING": 1, "CRITICAL": 2}.get(risk["level"], 0))
        at_risk += 1 if level >= 1 else 0
        trucks.append(
            {
                "shipment_id": s.id,
                "food_type": s.food_type,
                "hub_id": s.hub_id,
                "lat": hub.get("lat"),
                "lon": hub.get("lon"),
                "level": level,
                "risk": risk,
                "online": hub.get("online"),
                "temp_c": live["aggregates"]["temp_c"],
                "backlog": hub.get("backlog", 0),
                "origin": s.origin_name,
                "origin_lat": s.origin_lat,
                "origin_lon": s.origin_lon,
                "dest_lat": s.dest_lat,
                "dest_lon": s.dest_lon,
                "destination": s.dest_name,
            }
        )
    offline = (
        await session.execute(
            select(func.count())
            .select_from(Device)
            .where(Device.kind == "hub", Device.online.is_(False), Device.shipment_id.is_not(None))
        )
    ).scalar_one()
    return {
        "kpis": {
            "active_shipments": len(active),
            "at_risk": at_risk,
            "offline_hubs": offline,
            "verified_batches": await verifier.verified_batch_count(session, [s.id for s in active])
            if verifier
            else 0,
        },
        "trucks": trucks,
    }


@router.websocket("/ws")
async def ws_endpoint(ws: WebSocket, token: str, shipment_id: str | None = None) -> None:
    """Live push. Auth by ``?token=`` (browsers cannot set WebSocket headers)."""
    app = ws.app
    async with app.state.db.session_factory() as session:
        try:
            await user_from_token(session, app.state.settings, token)
        except HTTPException:
            await ws.close(code=4401)
            return
    await ws.accept()
    async with app.state.realtime.subscribe(shipment_id) as sub:
        await ws.send_json({"type": "hello", "shipment_id": shipment_id})

        async def reader() -> None:  # drain client pings / detect disconnects
            with contextlib.suppress(WebSocketDisconnect):
                while True:
                    await ws.receive_text()

        read_task = asyncio.create_task(reader())
        try:
            while not read_task.done():
                try:
                    msg = await asyncio.wait_for(sub.queue.get(), timeout=15)
                except TimeoutError:
                    await ws.send_json({"type": "ping"})
                    continue
                await ws.send_json(msg)
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            read_task.cancel()
