"""Commands to hubs (MQTT ``rakshak/{hub_id}/cmd``), logged in ``command_log``."""

from __future__ import annotations

import json
import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from ..db.base import utcnow
from ..db.models import CommandLog, Device
from .mqtt import CommandPublisher

log = logging.getLogger("rakshak.commands")

FLAP_VALUES = (0, 25, 50, 100)
# cmd -> does it need an argument
COMMANDS: dict[str, bool] = {
    "FLAP_SET": True,
    "FAN_ON": False,
    "FAN_OFF": False,
    "ALERT_WARNING": False,
    "ALERT_CRITICAL": False,
    "ALERT_CLEAR": False,
    "ACK_ALERT": False,
}


class CommandError(ValueError):
    pass


def validate(cmd: str, arg: int | None) -> None:
    if cmd not in COMMANDS:
        raise CommandError(f"unknown command {cmd!r}")
    if COMMANDS[cmd] and arg is None:
        raise CommandError(f"{cmd} needs an argument")
    if cmd == "FLAP_SET" and arg not in FLAP_VALUES:
        raise CommandError(f"FLAP_SET must be one of {FLAP_VALUES}")


async def send_command(
    session: AsyncSession,
    publisher: CommandPublisher,
    hub_id: str,
    cmd: str,
    arg: int | None = None,
    *,
    source: str,
    shipment_id: str | None = None,
) -> CommandLog:
    validate(cmd, arg)
    hub = await session.get(Device, hub_id)
    if hub is None or hub.kind != "hub":
        raise CommandError(f"unknown hub {hub_id}")
    row = CommandLog(
        cmd_id=str(uuid.uuid4()),
        hub_id=hub_id,
        shipment_id=shipment_id or hub.shipment_id,
        cmd=cmd,
        arg=arg,
        source=source,
        status="SENT",
        created_at=utcnow(),
    )
    session.add(row)
    # Commit before publishing: the hub's acknowledgement can come back faster than the caller's own commit.
    await session.commit()
    payload = {
        "id": row.cmd_id,
        "cmd": cmd,
        "arg": arg,
        "source": source,
        "ts": int(row.created_at.timestamp()),
    }
    try:
        await publisher.publish(f"rakshak/{hub_id}/cmd", json.dumps(payload).encode(), qos=1)
    except Exception as exc:
        log.warning("command %s to %s not published: %s", cmd, hub_id, exc)
        row.status = "FAILED"
        await session.commit()
    return row
