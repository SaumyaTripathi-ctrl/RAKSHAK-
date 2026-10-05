"""Verification: recompute everything from the database and compare with what the ledger holds.

Detects, among others:
  * a record body edited in the DB                      -> "stored hash does not match its content"
  * an edited *displayed* value (temp_c ...)             -> "displayed value differs from signed body"
  * a record deleted                                      -> "record(s) missing" + Merkle root mismatch
  * body + hash both rewritten                            -> chain link / Merkle root mismatch
  * the batch row itself rewritten                        -> DB root != ledger root
  * a hand-over edited, reordered or removed              -> hash / link / signature failures
  * the ledger file itself altered (local backend)        -> ledger integrity failure
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..codec import CodecError, compute_hash, unpack_body
from ..db.models import Batch, Handover, Record, Shipment
from ..services.custody import verify_handovers
from ..services.ingest import COLUMN_NAMES, record_columns
from .client import LedgerClient, LedgerError
from .merkle import merkle_proof, merkle_root

CACHE_TTL_S = 5.0


@dataclass
class BatchCheck:
    batch_id: int
    device_id: str
    first_seq: int
    last_seq: int
    leaf_count: int
    merkle_root: str
    ledger_ref: str | None
    status: str  # verified | tampered | pending | ledger_unreachable
    anchored_at: str
    problems: list[str] = field(default_factory=list)


def _close(a, b) -> bool:
    if a is None or b is None:
        return a is None and b is None
    if isinstance(a, bool) or isinstance(b, bool):
        return bool(a) == bool(b)
    if isinstance(a, int | float) and isinstance(b, int | float):
        return abs(float(a) - float(b)) < 1e-6
    return a == b


def check_record(r: Record) -> list[str]:
    """Self-consistency of one stored record (no ledger needed)."""
    out: list[str] = []
    if compute_hash(bytes.fromhex(r.prev_hash), r.body) != bytes.fromhex(r.hash):
        out.append(f"record {r.device_id}#{r.seq}: stored hash does not match its content (edited)")
        return out
    try:
        rec = unpack_body(r.body)
    except CodecError:
        return [*out, f"record {r.device_id}#{r.seq}: body is not a valid record"]
    expected = record_columns(rec)
    for name in COLUMN_NAMES:
        if not _close(getattr(r, name), expected.get(name)):
            out.append(
                f"record {r.device_id}#{r.seq}: displayed {name} ({getattr(r, name)}) differs from the signed body ({expected.get(name)})"
            )
    if not r.hash_ok or not r.chain_ok:
        out.append(f"record {r.device_id}#{r.seq}: flagged at ingest (hash/chain failure)")
    return out


class Verifier:
    def __init__(self, db, ledger: LedgerClient):
        self.db, self.ledger = db, ledger
        self._cache: dict[str, tuple[float, dict]] = {}

    # ------------------------------------------------------------ batches
    async def _check_batch(self, s: AsyncSession, b: Batch) -> BatchCheck:
        chk = BatchCheck(
            b.id, b.device_id, b.first_seq, b.last_seq, b.leaf_count, b.merkle_root, b.ledger_ref,
            "pending", b.created_at.isoformat(),
        )  # fmt: skip
        if not b.ledger_ref:
            return chk
        try:
            entry = await self.ledger.get(b.ledger_ref)
        except LedgerError as exc:
            chk.status, chk.problems = "ledger_unreachable", [str(exc)]
            return chk
        problems = chk.problems
        if entry is None or entry.kind != "BATCH":
            chk.status = "tampered"
            problems.append(f"ledger entry {b.ledger_ref} not found")
            return chk
        lp = entry.payload
        if lp.get("merkle_root") != b.merkle_root:
            problems.append(
                "batch record in the database does not match the ledger (root rewritten)"
            )
        for key, val in (
            ("first_seq", b.first_seq),
            ("last_seq", b.last_seq),
            ("leaf_count", b.leaf_count),
        ):
            if lp.get(key) != val:
                problems.append(
                    f"batch {key} in the database ({val}) differs from the ledger ({lp.get(key)})"
                )

        rows = list(
            (
                await s.execute(select(Record).where(Record.batch_id == b.id).order_by(Record.seq))
            ).scalars()
        )
        want = list(range(lp.get("first_seq", b.first_seq), lp.get("last_seq", b.last_seq) + 1))
        have = {r.seq for r in rows}
        missing = [q for q in want if q not in have]
        if missing:
            shown = ", ".join(str(q) for q in missing[:5]) + ("..." if len(missing) > 5 else "")
            problems.append(
                f"{len(missing)} record(s) deleted or detached from the batch (seq {shown})"
            )
        prev: Record | None = None
        for r in rows:
            problems.extend(check_record(r))
            if prev is not None and r.seq == prev.seq + 1 and r.prev_hash != prev.hash:
                problems.append(f"record {r.device_id}#{r.seq}: chain link broken")
            prev = r
        if rows:
            recomputed = merkle_root([bytes.fromhex(r.hash) for r in rows]).hex()
            if recomputed != lp.get("merkle_root"):
                problems.append(
                    f"Merkle root mismatch: recomputed {recomputed[:12]}... != ledger {str(lp.get('merkle_root'))[:12]}..."
                )
        chk.status = "tampered" if problems else "verified"
        return chk

    # ------------------------------------------------------------ shipment
    async def verify_shipment(self, s: AsyncSession, shipment_id: str) -> dict:
        batches = list(
            (
                await s.execute(
                    select(Batch).where(Batch.shipment_id == shipment_id).order_by(Batch.id)
                )
            ).scalars()
        )
        checks = [await self._check_batch(s, b) for b in batches]

        unanchored = list(
            (
                await s.execute(
                    select(Record)
                    .where(Record.shipment_id == shipment_id, Record.batch_id.is_(None))
                    .order_by(Record.device_id, Record.seq)
                )
            ).scalars()
        )
        unanchored_problems: list[str] = []
        for r in unanchored:
            unanchored_problems.extend(check_record(r))

        handovers = list(
            (
                await s.execute(
                    select(Handover)
                    .where(Handover.shipment_id == shipment_id)
                    .order_by(Handover.id)
                )
            ).scalars()
        )
        ho_checks = []
        chain = verify_handovers(handovers)
        batch_roots = {b.id: b.merkle_root for b in batches}
        for h, c in zip(handovers, chain, strict=True):
            problems = [c.reason] if not c.ok else []
            ok_anchor: bool | None = None
            if h.ledger_ref:
                try:
                    entry = await self.ledger.get(h.ledger_ref)
                except LedgerError as exc:
                    problems.append(str(exc))
                    entry = None
                else:
                    if entry is None or entry.kind != "HANDOVER":
                        problems.append(f"ledger entry {h.ledger_ref} not found")
                    else:
                        if entry.payload.get("handover_hash") != h.payload_hash:
                            problems.append("hand-over differs from the ledger entry (edited)")
                        up_to = [
                            batch_roots[i]
                            for i in sorted(batch_roots)
                            if h.batch_id is not None and i <= h.batch_id
                        ]
                        if merkle_root(
                            [bytes.fromhex(x) for x in up_to]
                        ).hex() != entry.payload.get("batches_root"):
                            problems.append(
                                "sensor history at this hand-over no longer matches the ledger"
                            )
                ok_anchor = not problems
            ho_checks.append(
                {
                    "id": h.id, "stage": h.stage, "anchored": bool(h.ledger_ref), "ledger_ref": h.ledger_ref,
                    "ok": not problems and (ok_anchor is not False), "problems": problems,
                    "organisation": h.organisation, "at": h.created_at.isoformat(),
                }
            )  # fmt: skip

        integrity = await self.ledger.integrity()
        anchored_records = sum(c.leaf_count for c in checks if c.status == "verified")
        total_records = (
            await s.execute(
                select(func.count()).select_from(Record).where(Record.shipment_id == shipment_id)
            )
        ).scalar_one()
        tamper = (
            any(c.status == "tampered" for c in checks)
            or bool(unanchored_problems)
            or any(not h["ok"] for h in ho_checks)
            or not integrity.ok
        )
        if tamper:
            status = "TAMPERED"
        elif any(c.status == "ledger_unreachable" for c in checks):
            status = "LEDGER_UNREACHABLE"
        elif not any(c.status == "verified" for c in checks):
            status = "PENDING"
        elif unanchored:
            status = "PARTIAL"
        else:
            status = "VERIFIED"
        result = {
            "shipment_id": shipment_id,
            "status": status,
            "verified": status in ("VERIFIED", "PARTIAL"),
            "tampered": status == "TAMPERED",
            "anchored_records": anchored_records,
            "unanchored_records": len(unanchored),
            "total_records": total_records,
            "coverage": round(anchored_records / total_records, 4) if total_records else 0.0,
            "batches": [asdict(c) for c in checks],
            "handovers": ho_checks,
            "unanchored_problems": unanchored_problems,
            "ledger": {
                "backend": self.ledger.name,
                "decentralised": self.ledger.decentralised,
                "integrity_ok": integrity.ok,
                "entries": integrity.entries,
                "problem": integrity.problem,
            },
            "checked_at": int(time.time()),
        }
        self._cache[shipment_id] = (time.monotonic(), result)
        return result

    async def cached(self, s: AsyncSession, shipment_id: str) -> dict:
        hit = self._cache.get(shipment_id)
        if hit and time.monotonic() - hit[0] < CACHE_TTL_S:
            return hit[1]
        return await self.verify_shipment(s, shipment_id)

    # ------------------------------------------------------------ views for other endpoints
    async def public_summary(self, s: AsyncSession, shipment: Shipment) -> dict:
        r = await self.cached(s, shipment.id)
        return {
            "verified": r["verified"],
            "status": r["status"],
            "backend": r["ledger"]["backend"],
            "decentralised": r["ledger"]["decentralised"],
            "anchored_records": r["anchored_records"],
            "total_records": r["total_records"],
            "coverage": r["coverage"],
            "batches": len([b for b in r["batches"] if b["status"] == "verified"]),
            "handovers_anchored": len([h for h in r["handovers"] if h["anchored"] and h["ok"]]),
            "note": None
            if r["ledger"]["decentralised"]
            else "Demo ledger: tamper-evident but run by a single party (no independent peers).",
        }

    async def verified_batch_count(
        self, s: AsyncSession, shipment_ids: list[str] | None = None
    ) -> int:
        """Verified batches across `shipment_ids` (default: every shipment with batches).

        The fleet overview passes only the active shipments: verifying all history on every page load
        does not scale (hundreds of shipments stalled the API).
        """
        if shipment_ids is None:
            shipment_ids = (await s.execute(select(Batch.shipment_id).distinct())).scalars().all()
        ids = shipment_ids
        total = 0
        for sid in ids:
            r = await self.cached(s, sid)
            total += len([b for b in r["batches"] if b["status"] == "verified"])
        return total

    async def proof(self, s: AsyncSession, device_id: str, seq: int) -> dict | None:
        rec = (
            await s.execute(select(Record).where(Record.device_id == device_id, Record.seq == seq))
        ).scalar_one_or_none()
        if rec is None or rec.batch_id is None:
            return None
        batch = await s.get(Batch, rec.batch_id)
        rows = list(
            (
                await s.execute(
                    select(Record).where(Record.batch_id == batch.id).order_by(Record.seq)
                )
            ).scalars()
        )
        hashes = [bytes.fromhex(r.hash) for r in rows]
        idx = next(i for i, r in enumerate(rows) if r.seq == seq)
        return {
            "device_id": device_id,
            "seq": seq,
            "record_hash": rec.hash,
            "batch_id": batch.id,
            "merkle_root": batch.merkle_root,
            "ledger_ref": batch.ledger_ref,
            "proof": [{"hash": h.hex(), "side": side} for h, side in merkle_proof(hashes, idx)],
            "method": "RFC 6962: leaf=SHA256(0x00||record_hash), node=SHA256(0x01||left||right)",
        }
