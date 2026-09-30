"""Devices (hubs/tags), provisioning and commands."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select

from ...codec import derive_device_key
from ...db.models import Device, Role, User
from ...services.commands import CommandError, send_command
from ..deps import CurrentUser, Session, SettingsDep, require_roles
from ..schemas import CommandOut, CommandRequest, DeviceCreate, DeviceOut, ProvisioningOut

router = APIRouter(prefix="/api/devices", tags=["devices"])

Admin = Annotated[User, Depends(require_roles(Role.ADMIN.value))]
CommandUser = Annotated[
    User, Depends(require_roles(Role.ADMIN.value, Role.FPO.value, Role.DRIVER.value))
]


@router.get("", response_model=list[DeviceOut])
async def list_devices(session: Session, _: CurrentUser, kind: str | None = None) -> list[Device]:
    q = select(Device).order_by(Device.id)
    if kind:
        q = q.where(Device.kind == kind)
    return list((await session.execute(q)).scalars())


@router.get("/{device_id}", response_model=DeviceOut)
async def get_device(device_id: str, session: Session, _: CurrentUser) -> Device:
    d = await session.get(Device, device_id)
    if d is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown device")
    return d


@router.post("", response_model=ProvisioningOut, status_code=status.HTTP_201_CREATED)
async def create_device(
    body: DeviceCreate, session: Session, _: Admin, settings: SettingsDep
) -> ProvisioningOut:
    if await session.get(Device, body.id) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "device already exists")
    d = Device(id=body.id, kind=body.kind, name=body.name, hub_id=body.hub_id, key_epoch=0)
    session.add(d)
    await session.commit()
    key = derive_device_key(settings.master_key, d.id, d.key_epoch)
    return ProvisioningOut(
        device=DeviceOut.model_validate(d), key_epoch=d.key_epoch, device_key_hex=key.hex()
    )


@router.post("/{device_id}/rotate-key", response_model=ProvisioningOut)
async def rotate_key(
    device_id: str, session: Session, _: Admin, settings: SettingsDep
) -> ProvisioningOut:
    d = await session.get(Device, device_id)
    if d is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown device")
    if d.key_epoch >= 0xFFFF:
        raise HTTPException(status.HTTP_409_CONFLICT, "key_epoch exhausted")
    d.key_epoch += 1  # seq is NOT reset: the new key makes (key, nonce) pairs unique anyway
    await session.commit()
    key = derive_device_key(settings.master_key, d.id, d.key_epoch)
    return ProvisioningOut(
        device=DeviceOut.model_validate(d), key_epoch=d.key_epoch, device_key_hex=key.hex()
    )


@router.post("/{hub_id}/cmd", response_model=CommandOut, status_code=status.HTTP_202_ACCEPTED)
async def command(
    hub_id: str, body: CommandRequest, session: Session, user: CommandUser, request: Request
) -> CommandOut:
    try:
        row = await send_command(
            session,
            request.app.state.publisher,
            hub_id,
            body.cmd,
            body.arg,
            source=f"user:{user.username}",
            shipment_id=body.shipment_id,
        )
    except CommandError as exc:
        raise HTTPException(422, str(exc)) from exc
    await session.commit()
    return CommandOut.model_validate(row)
