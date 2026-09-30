"""Anchoring: Merkle roots of record-hash batches and hand-overs go onto the ledger.

* A **batch** is a contiguous ``seq`` run of one device's records within one shipment. It is anchored
  every ``batch_size`` records, and any remainder is flushed on hand-over / shipment close.
* A **hand-over** entry binds the signed custody event to the whole sensor history so far:
  ``batches_root`` = Merkle root over all batch roots of the shipment at that moment.
"""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import Settings
from ..db.base import Database, utcnow
from ..db.models import Batch, EventKind, Handover, Record, Severity
from ..services.ingest import IngestResult, event_to_dict, make_event
from ..services.realtime import RealtimeHub
from .client import LedgerClient, LedgerError
from .merkle import merkle_root

log = logging.getLogger("rakshak.ledger")


class Anchorer:
    def __init__(
        self, db: Database, settings: Settings, ledger: LedgerClient, realtime: RealtimeHub
    ):
        self.db, self.settings, self.ledger, self.realtime = db, settings, ledger, realtime
        self._lock = asyncio.Lock()

    # ---------------------------------------------------------------- listener
    async def on_ingest(self, result: IngestResult) -> None:
        if not result.stored or not result.device_id or not result.shipment_id:
            return
        async with self._lock:
            await self._anchor_full_batches(result.device_id, result.shipment_id)

    # ---------------------------------------------------------------- public API
    async def anchor_shipment(self, shipment_id: str, reason: str = "flush") -> list[Batch]:
        async with self._lock:
            return await self._flush_shipment(shipment_id, reason)

    async def anchor_handover(self, handover_id: int) -> str | None:
        async with self._lock:
            async with self.db.session_factory() as s:
                h = await s.get(Handover, handover_id)
                if h is None:
                    return None
                shipment_id = h.shipment_id
            await self._flush_shipment(shipment_id, "handover")
            async with self.db.session_factory() as s:
                h = await s.get(Handover, handover_id)
                batches = list(
                    (
                        await s.execute(
                            select(Batch).where(Batch.shipment_id == shipment_id).order_by(Batch.id)
                        )
                    ).scalars()
                )
                payload = {
                    "shipment_id": shipment_id,
                    "stage": h.stage,
                    "handover_hash": h.payload_hash,
                    "prev_hash": h.prev_hash,
                    "signature": h.signature,
                    "public_key": h.public_key,
                    "batches_root": merkle_root(
                        [bytes.fromhex(b.merkle_root) for b in batches]
                    ).hex(),
                    "batch_count": len(batches),
                    "ts": int(utcnow().timestamp()),
                }
                try:
                    ref = await self.ledger.submit("HANDOVER", payload)
                except LedgerError as exc:
                    log.warning("hand-over %s not anchored: %s", handover_id, exc)
                    return None
                h.ledger_ref = ref
                h.batch_id = batches[-1].id if batches else None
                ev = make_event(
                    EventKind.LEDGER_ANCHORED,
                    Severity.INFO,
                    f"Hand-over {h.stage} anchored on the {self.ledger.name} ledger",
                    shipment_id=shipment_id,
                    data={"ledger_ref": ref, "stage": h.stage},
                )
                s.add(ev)
                await s.commit()
                self.realtime.publish({"type": "event", "data": event_to_dict(ev)}, shipment_id)
                return ref

    # ---------------------------------------------------------------- internals
    async def _flush_shipment(self, shipment_id: str, reason: str) -> list[Batch]:
        async with self.db.session_factory() as s:
            devices = list(
                (
                    await s.execute(
                        select(Record.device_id)
                        .where(Record.shipment_id == shipment_id, Record.batch_id.is_(None))
                        .distinct()
                    )
                ).scalars()
            )
        out: list[Batch] = []
        for dev in devices:
            out += await self._anchor_full_batches(dev, shipment_id)
            out += await self._anchor_remainder(dev, shipment_id, reason)
        return out

    @staticmethod
    def _runs(rows: list[tuple[int, int, str]]) -> list[list[tuple[int, int, str]]]:
        """Split (seq, id, hash) rows into contiguous seq runs."""
        runs: list[list[tuple[int, int, str]]] = []
        for row in rows:
            if runs and row[0] == runs[-1][-1][0] + 1:
                runs[-1].append(row)
            else:
                runs.append([row])
        return runs

    async def _unbatched(self, s: AsyncSession, device_id: str, shipment_id: str):
        q = (
            select(Record.seq, Record.id, Record.hash)
            .where(
                Record.device_id == device_id,
                Record.shipment_id == shipment_id,
                Record.batch_id.is_(None),
            )
            .order_by(Record.seq)
        )
        return [tuple(r) for r in (await s.execute(q)).all()]

    async def _anchor_full_batches(self, device_id: str, shipment_id: str) -> list[Batch]:
        out: list[Batch] = []
        n = self.settings.batch_size
        while True:
            async with self.db.session_factory() as s:
                runs = self._runs(await self._unbatched(s, device_id, shipment_id))
                run = next((r for r in runs if len(r) >= n), None)
                if run is None:
                    return out
                batch = await self._anchor_run(s, device_id, shipment_id, run[:n], "size")
            if batch is None:
                return out
            out.append(batch)

    async def _anchor_remainder(self, device_id: str, shipment_id: str, reason: str) -> list[Batch]:
        out: list[Batch] = []
        async with self.db.session_factory() as s:
            runs = self._runs(await self._unbatched(s, device_id, shipment_id))
        for run in runs:
            async with self.db.session_factory() as s:
                batch = await self._anchor_run(s, device_id, shipment_id, run, reason)
            if batch is not None:
                out.append(batch)
        return out

    async def _anchor_run(
        self,
        s: AsyncSession,
        device_id: str,
        shipment_id: str,
        run: list[tuple[int, int, str]],
        reason: str,
    ) -> Batch | None:
        from .stage import current_stage  # local import: avoids a cycle with custody

        root = merkle_root([bytes.fromhex(h) for _, _, h in run])
        batch = Batch(
            shipment_id=shipment_id,
            device_id=device_id,
            first_seq=run[0][0],
            last_seq=run[-1][0],
            leaf_count=len(run),
            merkle_root=root.hex(),
            reason=reason,
            created_at=utcnow(),
        )
        s.add(batch)
        await s.flush()
        payload = {
            "shipment_id": shipment_id,
            "device_id": device_id,
            "batch_id": batch.id,
            "first_seq": batch.first_seq,
            "last_seq": batch.last_seq,
            "leaf_count": batch.leaf_count,
            "merkle_root": batch.merkle_root,
            "stage": await current_stage(s, shipment_id),
            "ts": int(batch.created_at.timestamp()),
        }
        try:
            batch.ledger_ref = await self.ledger.submit("BATCH", payload)
        except LedgerError as exc:
            log.warning(
                "batch for %s/%s not anchored (will retry): %s", shipment_id, device_id, exc
            )
            await s.rollback()
            return None
        await s.execute(
            update(Record)
            .where(Record.id.in_([rid for _, rid, _ in run]))
            .values(batch_id=batch.id)
        )
        ev = make_event(
            EventKind.LEDGER_ANCHORED,
            Severity.INFO,
            f"{device_id}: {batch.leaf_count} records (seq {batch.first_seq}-{batch.last_seq}) anchored on the {self.ledger.name} ledger",
            shipment_id=shipment_id,
            device_id=device_id,
            data={
                "batch_id": batch.id,
                "ledger_ref": batch.ledger_ref,
                "merkle_root": batch.merkle_root,
            },
        )
        s.add(ev)
        await s.commit()
        self.realtime.publish({"type": "event", "data": event_to_dict(ev)}, shipment_id)
        return batch
