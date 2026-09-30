"""In-process pub/sub used by the WebSocket endpoint."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from dataclasses import dataclass, field


@dataclass(eq=False)
class Subscription:
    shipment_id: str | None  # None = everything
    queue: asyncio.Queue = field(default_factory=lambda: asyncio.Queue(maxsize=500))


class RealtimeHub:
    def __init__(self) -> None:
        self._subs: set[Subscription] = set()

    @contextlib.asynccontextmanager
    async def subscribe(self, shipment_id: str | None = None) -> AsyncIterator[Subscription]:
        sub = Subscription(shipment_id)
        self._subs.add(sub)
        try:
            yield sub
        finally:
            self._subs.discard(sub)

    def publish(self, message: dict, shipment_id: str | None = None) -> None:
        """Non-blocking; a slow subscriber loses its oldest message rather than stalling ingest."""
        for sub in list(self._subs):
            if sub.shipment_id is not None and shipment_id != sub.shipment_id:
                continue
            if sub.queue.full():
                with contextlib.suppress(asyncio.QueueEmpty):
                    sub.queue.get_nowait()
            sub.queue.put_nowait(message)

    @property
    def subscriber_count(self) -> int:
        return len(self._subs)
