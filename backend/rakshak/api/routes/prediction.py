"""Risk history, rerouting, food types, facilities."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from rakshak_ml.bands import get_band, load_bands
from sqlalchemy import select

from ...db.models import RiskPoint, Role, Shipment, User
from ...prediction.facilities import compatible, haversine_km
from ..deps import CurrentUser, Session, require_roles

router = APIRouter(tags=["prediction"])

Responder = Annotated[
    User, Depends(require_roles(Role.ADMIN.value, Role.FPO.value, Role.DRIVER.value))
]
Admin = Annotated[User, Depends(require_roles(Role.ADMIN.value))]


async def _shipment(session, shipment_id: str) -> Shipment:
    s = await session.get(Shipment, shipment_id)
    if s is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown shipment")
    return s


def _predictor(request: Request):
    p = getattr(request.app.state, "predictor", None)
    if p is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "prediction is not available (no trained models found)",
        )
    return p


@router.get("/api/food-types")
async def food_types(_: CurrentUser) -> list[dict]:
    """Storage bands for the food-type selector. Values are PLACEHOLDERS marked TODO-verify."""
    return [
        {
            "food_type": b.food_type,
            "min_temp": b.min_temp,
            "max_temp": b.max_temp,
            "min_rh": b.min_rh,
            "max_rh": b.max_rh,
            "ethylene_sensitive": b.ethylene_sensitive,
            "ethylene_producer": b.ethylene_producer,
            "source": b.source,
            "verification_status": b.verification_status,
        }
        for b in load_bands().values()
    ]


@router.get("/api/facilities")
async def facilities(
    _: CurrentUser,
    request: Request,
    food_type: str | None = None,
    lat: float | None = None,
    lon: float | None = None,
    radius_km: Annotated[float, Query(gt=0, le=2000)] = 300,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
) -> dict:
    """Facilities (SYNTHETIC unless the CSV was replaced - see ``data_source``)."""
    items = list(request.app.state.facilities)
    if food_type:
        try:
            band = get_band(food_type)
        except KeyError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
        items = [f for f in items if compatible(f, band)]
    if lat is not None and lon is not None:
        items = [f for f in items if haversine_km(lat, lon, f.lat, f.lng) <= radius_km]
        items.sort(key=lambda f: haversine_km(lat, lon, f.lat, f.lng))
    items = items[:limit]
    return {
        "count": len(items),
        "data_sources": sorted({f.data_source for f in items}),
        "facilities": [f.to_dict() for f in items],
    }


@router.get("/api/shipments/{shipment_id}/risk")
async def risk_history(
    shipment_id: str,
    session: Session,
    _: CurrentUser,
    since: int | None = None,
    limit: Annotated[int, Query(ge=1, le=5000)] = 1500,
) -> dict:
    await _shipment(session, shipment_id)
    q = select(RiskPoint).where(RiskPoint.shipment_id == shipment_id).order_by(RiskPoint.t)
    if since is not None:
        q = q.where(RiskPoint.t >= since)
    rows = list((await session.execute(q)).scalars())
    step = max(1, len(rows) // limit)
    return {
        "shipment_id": shipment_id,
        "points": [
            {
                "t": r.t,
                "risk": round(r.risk, 1),
                "rsl_hours": round(r.rsl_hours, 1),
                "level": r.level,
                "profile": r.profile,
            }
            for r in rows[::step]
        ],
    }


@router.get("/api/shipments/{shipment_id}/reroute")
async def get_reroute(
    shipment_id: str, session: Session, _: CurrentUser, request: Request, refresh: bool = False
) -> dict:
    """Current detour recommendation (computed automatically on CRITICAL; ``refresh`` recomputes)."""
    await _shipment(session, shipment_id)
    pred = _predictor(request)
    doc = pred.reroute_state(shipment_id)
    if doc is None or refresh:
        doc = await pred.compute_reroute(shipment_id)
        if doc is not None:
            accepted = (pred.reroute_state(shipment_id) or {}).get("accepted_facility_id")
            doc = {**doc, "accepted_facility_id": accepted}
    if doc is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "no position known yet for this shipment")
    return doc


class AcceptReroute(BaseModel):
    facility_id: str = Field(min_length=1, max_length=32)


@router.post("/api/shipments/{shipment_id}/reroute/accept")
async def accept_reroute(
    shipment_id: str, body: AcceptReroute, session: Session, user: Responder, request: Request
) -> dict:
    await _shipment(session, shipment_id)
    chosen = await _predictor(request).accept_reroute(shipment_id, body.facility_id, user.username)
    if chosen is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "facility is not part of the current recommendation"
        )
    return chosen


class ProfileBody(BaseModel):
    model_profile: str = Field(pattern="^(real|demo)$")


@router.put("/api/shipments/{shipment_id}/model-profile")
async def set_model_profile(
    shipment_id: str, body: ProfileBody, session: Session, _: Admin, request: Request
) -> dict:
    """Switch a shipment between the real and the time-compressed *demo* model pair (admin only)."""
    shipment = await _shipment(session, shipment_id)
    shipment.model_profile = body.model_profile
    await session.commit()
    pred = getattr(request.app.state, "predictor", None)
    if pred is not None:
        pred.trackers.pop(shipment_id, None)  # rebuilt with the new model on the next sample
    return {"shipment_id": shipment_id, "model_profile": body.model_profile}


@router.get("/api/route")
async def road_route(
    request: Request,
    _: CurrentUser,
    from_lat: float = Query(ge=-90, le=90),
    from_lon: float = Query(ge=-180, le=180),
    to_lat: float = Query(ge=-90, le=90),
    to_lon: float = Query(ge=-180, le=180),
) -> dict:
    """Road geometry between two points (OSRM, cached) for maps and the simulator; straight line if unavailable."""
    p = getattr(request.app.state, "predictor", None)
    a, b = (from_lat, from_lon), (to_lat, to_lon)
    if p is None:
        d = haversine_km(a[0], a[1], b[0], b[1])
        return {
            "distance_km": round(d, 2),
            "duration_min": round(d / 30 * 60, 1),
            "source": "haversine",
            "status": "estimated",
            "geometry": [list(a), list(b)],
            "note": "road routing unavailable; straight line",
        }
    return (await p.router.route(a, b)).to_dict()
