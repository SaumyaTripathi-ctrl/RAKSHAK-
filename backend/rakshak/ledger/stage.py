from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import Handover


async def current_stage(s: AsyncSession, shipment_id: str) -> str:
    """Custody stage at this moment = the stage of the latest hand-over (or UNASSIGNED)."""
    stage = (
        await s.execute(
            select(Handover.stage)
            .where(Handover.shipment_id == shipment_id)
            .order_by(Handover.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return stage or "UNASSIGNED"
