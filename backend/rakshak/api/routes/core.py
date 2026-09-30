"""Health, auth and the public provenance document."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import select, text

from ... import __version__
from ...db.models import Shipment, User
from ...security import create_token, verify_password
from ...services.views import public_provenance
from ..deps import CurrentUser, Session, SettingsDep
from ..schemas import LoginRequest, TokenOut, UserOut

router = APIRouter()


@router.get("/health", tags=["system"])
async def health(request: Request, session: Session) -> dict:
    await session.execute(text("SELECT 1"))
    bridge = getattr(request.app.state, "bridge", None)
    settings = request.app.state.settings
    return {
        "status": "ok",
        "version": __version__,
        "db": "ok",
        "mqtt": {"enabled": settings.mqtt_enabled, "connected": bool(bridge and bridge.connected)},
        "ledger": settings.ledger_backend,
        "dev_secrets": settings.using_dev_secrets,
    }


@router.post("/api/auth/login", response_model=TokenOut, tags=["auth"])
async def login(body: LoginRequest, session: Session, settings: SettingsDep) -> TokenOut:
    user = (
        await session.execute(select(User).where(User.username == body.username))
    ).scalar_one_or_none()
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "incorrect username or password")
    return TokenOut(
        access_token=create_token(settings, user.username, user.role),
        user=UserOut.model_validate(user),
    )


@router.get("/api/auth/me", response_model=UserOut, tags=["auth"])
async def me(user: CurrentUser) -> User:
    return user


@router.get("/api/public/shipments/{shipment_id}", tags=["public"])
async def public_shipment(shipment_id: str, request: Request, session: Session) -> dict:
    """Read-only provenance document behind the QR code. No login; no personal data or keys."""
    shipment = await session.get(Shipment, shipment_id)
    if shipment is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown shipment")
    doc = await public_provenance(session, shipment)
    verifier = getattr(request.app.state, "verifier", None)
    if verifier is not None:
        doc["ledger"] = await verifier.public_summary(session, shipment)
    return doc
