"""Anchoring + verification end to end, including every way of tampering with the database."""

from __future__ import annotations

import hashlib
import json

import pytest
from rakshak.codec import compute_hash, pack_body, unpack_body
from rakshak.db.models import Batch, Handover, Record
from rakshak.ledger.client import LedgerError
from rakshak.ledger.merkle import verify_proof
from rakshak.services.custody import canonical_payload
from sqlalchemy import delete, select

from .conftest import login
from .helpers import T0, FakeDevice

SHIP = "RKS-26-000001"


async def feed(app, n=12, *, device="TAG-0001"):
    dev = FakeDevice(device, SHIP)
    for i in range(n):
        await app.state.ingestor.ingest_frame(
            dev.tag(T0 + 60 * i, temp=10 + i * 0.1), via_hub="HUB-0001"
        )
    return dev


async def verify(client, hdr, sid=SHIP):
    r = await client.get(f"/api/verify/{sid}", headers=hdr)
    assert r.status_code == 200, r.text
    return r.json()


async def mutate(app, fn):
    async with app.state.db.session_factory() as s:
        await fn(s)
        await s.commit()


async def test_batches_anchor_every_n_and_remainder_on_flush(app, client, fpo):
    await feed(app, 12)
    v = await verify(client, fpo)
    assert len(v["batches"]) == 2 and v["unanchored_records"] == 2
    assert (
        v["status"] == "PARTIAL"
        and v["verified"]
        and v["coverage"] == pytest.approx(10 / 12, abs=1e-3)
    )
    assert all(
        b["status"] == "verified" and b["ledger_ref"].startswith("local:") for b in v["batches"]
    )
    r = await client.post(f"/api/shipments/{SHIP}/anchor", headers=fpo)
    assert r.json()["anchored_batches"] == 1
    v = await verify(client, fpo)
    assert (v["status"], v["unanchored_records"], len(v["batches"])) == ("VERIFIED", 0, 3)
    assert [b["leaf_count"] for b in v["batches"]] == [5, 5, 2]
    assert v["ledger"]["backend"] == "local" and v["ledger"]["integrity_ok"]


async def test_nothing_anchored_is_pending_not_verified(app, client, fpo):
    await feed(app, 3)
    v = await verify(client, fpo)
    assert v["status"] == "PENDING" and v["verified"] is False and v["batches"] == []


async def test_unknown_shipment_404(client, fpo):
    assert (await client.get("/api/verify/RKS-00-000000", headers=fpo)).status_code == 404


async def anchored(app, client, fpo, n=10):
    await feed(app, n)
    v = await verify(client, fpo)
    assert v["status"] == "VERIFIED"


async def test_tamper_record_body_in_db(app, client, fpo):
    await anchored(app, client, fpo)

    async def edit(s):
        r = (
            await s.execute(select(Record).where(Record.device_id == "TAG-0001", Record.seq == 3))
        ).scalar_one()
        b = bytearray(r.body)
        b[42] ^= 0x10  # change the stored temperature bytes
        r.body = bytes(b)

    await mutate(app, edit)
    v = await verify(client, fpo)
    assert v["status"] == "TAMPERED" and v["tampered"] and not v["verified"]
    probs = [p for b in v["batches"] for p in b["problems"]]
    assert any("TAG-0001#3" in p and "stored hash does not match" in p for p in probs)


async def test_tamper_displayed_value_only(app, client, fpo):
    """The UI reads temp_c; changing just that column must not go unnoticed."""
    await anchored(app, client, fpo)

    async def edit(s):
        r = (
            await s.execute(select(Record).where(Record.device_id == "TAG-0001", Record.seq == 4))
        ).scalar_one()
        r.temp_c = 4.0  # "it was always cold"

    await mutate(app, edit)
    v = await verify(client, fpo)
    assert v["status"] == "TAMPERED"
    assert any("displayed temp_c" in p for b in v["batches"] for p in b["problems"])


async def test_tamper_delete_record(app, client, fpo):
    await anchored(app, client, fpo)

    async def edit(s):
        await s.execute(delete(Record).where(Record.device_id == "TAG-0001", Record.seq == 2))

    await mutate(app, edit)
    v = await verify(client, fpo)
    assert v["status"] == "TAMPERED"
    probs = [p for b in v["batches"] for p in b["problems"]]
    assert any("deleted" in p and "2" in p for p in probs) and any(
        "Merkle root mismatch" in p for p in probs
    )


async def test_tamper_rewrite_body_and_hash_still_caught_by_ledger(app, client, fpo):
    """A careful attacker fixes body, columns and the record's own hash. The next record's prev_hash
    and - decisively - the Merkle root on the ledger still expose it."""
    await anchored(app, client, fpo)

    async def edit(s):
        r = (
            await s.execute(select(Record).where(Record.device_id == "TAG-0001", Record.seq == 3))
        ).scalar_one()
        rec = unpack_body(r.body)
        forged = type(rec)(**{**rec.__dict__, "temp_x100": 500})
        r.body = pack_body(forged)
        r.hash = compute_hash(bytes.fromhex(r.prev_hash), r.body).hex()
        r.temp_c = 5.0

    await mutate(app, edit)
    v = await verify(client, fpo)
    assert v["status"] == "TAMPERED"
    probs = [p for b in v["batches"] for p in b["problems"]]
    assert any("chain link broken" in p for p in probs) and any(
        "Merkle root mismatch" in p for p in probs
    )


async def test_tamper_rewrite_chain_and_batch_row_caught_by_ledger(app, client, fpo):
    """Attacker re-hashes the *whole* chain and rewrites the batch row: only the ledger copy gives it away."""
    await anchored(app, client, fpo)

    async def edit(s):
        rows = list(
            (
                await s.execute(
                    select(Record)
                    .where(Record.device_id == "TAG-0001", Record.batch_id == 1)
                    .order_by(Record.seq)
                )
            ).scalars()
        )
        prev = bytes.fromhex(rows[0].prev_hash)
        for r in rows:
            if r.seq == 1:
                rec = unpack_body(r.body)
                r.body = pack_body(type(rec)(**{**rec.__dict__, "temp_x100": 300}))
                r.temp_c = 3.0
            r.prev_hash = prev.hex()
            r.hash = compute_hash(prev, r.body).hex()
            prev = bytes.fromhex(r.hash)
        from rakshak.ledger.merkle import merkle_root

        batch = await s.get(Batch, 1)
        batch.merkle_root = merkle_root([bytes.fromhex(r.hash) for r in rows]).hex()

    await mutate(app, edit)
    v = await verify(client, fpo)
    assert v["status"] == "TAMPERED"
    assert any("does not match the ledger" in p for b in v["batches"] for p in b["problems"])


async def test_tamper_ledger_file_detected(app, client, fpo):
    await anchored(app, client, fpo)
    path = app.state.ledger.path
    lines = path.read_text().splitlines()
    row = json.loads(lines[1])
    row["payload"]["leaf_count"] = 1
    lines[1] = json.dumps(row, sort_keys=True, separators=(",", ":"))
    path.write_text("\n".join(lines) + "\n")
    v = await verify(client, fpo)
    assert v["status"] == "TAMPERED" and v["ledger"]["integrity_ok"] is False
    st = (await client.get("/api/ledger/status", headers=fpo)).json()
    assert st["integrity_ok"] is False


async def test_unanchored_edit_detected_too(app, client, fpo):
    await feed(app, 12)  # 2 unanchored

    async def edit(s):
        r = (
            await s.execute(select(Record).where(Record.device_id == "TAG-0001", Record.seq == 11))
        ).scalar_one()
        r.temp_c = 99.0

    await mutate(app, edit)
    v = await verify(client, fpo)
    assert v["status"] == "TAMPERED" and v["unanchored_problems"]


async def test_handover_anchoring_and_tamper(app, client, fpo):
    driver = await login(client, "driver")
    await feed(app, 7)  # below batch size -> flushed by the hand-over
    r = await client.post(
        f"/api/shipments/{SHIP}/handover",
        json={"stage": "FARM", "location": "Ratnagiri"},
        headers=fpo,
    )
    assert r.status_code == 201 and r.json()["ledger_ref"].startswith("local:")
    r2 = await client.post(
        f"/api/shipments/{SHIP}/handover", json={"stage": "TRANSPORT"}, headers=driver
    )
    assert r2.json()["ledger_ref"] and r2.json()["batch_id"] is not None
    v = await verify(client, fpo)
    assert v["status"] == "VERIFIED" and [h["ok"] and h["anchored"] for h in v["handovers"]] == [
        True,
        True,
    ]
    entries = (await client.get(f"/api/ledger/entries?shipment_id={SHIP}", headers=fpo)).json()
    kinds = [e["kind"] for e in entries]
    assert kinds.count("HANDOVER") == 2 and "BATCH" in kinds
    batch_entry = next(e for e in entries if e["kind"] == "BATCH")
    assert batch_entry["payload"]["stage"] in ("FARM", "UNASSIGNED")  # stage at anchoring time

    async def edit(s):
        h = (await s.execute(select(Handover).order_by(Handover.id))).scalars().first()
        h.notes = "rewritten"

    await mutate(app, edit)
    v = await verify(client, fpo)
    assert v["status"] == "TAMPERED" and not v["handovers"][0]["ok"]


async def test_handover_binds_sensor_history(app, client, fpo):
    """Rewriting the *batch list* after a hand-over (history change) no longer matches batches_root."""
    await feed(app, 5)
    await client.post(f"/api/shipments/{SHIP}/handover", json={"stage": "FARM"}, headers=fpo)
    await feed(app, 0)

    async def edit(s):
        b = await s.get(Batch, 1)
        b.merkle_root = "ab" * 32

    await mutate(app, edit)
    v = await verify(client, fpo)
    assert v["status"] == "TAMPERED"
    assert any("no longer matches the ledger" in p for h in v["handovers"] for p in h["problems"])


async def test_inclusion_proof_endpoint(app, client, fpo):
    await anchored(app, client, fpo)
    p = (await client.get("/api/ledger/proof/TAG-0001/7", headers=fpo)).json()
    proof = [(bytes.fromhex(x["hash"]), x["side"]) for x in p["proof"]]
    assert verify_proof(bytes.fromhex(p["record_hash"]), proof, bytes.fromhex(p["merkle_root"]))
    entry = await app.state.ledger.get(p["ledger_ref"])
    assert entry.payload["merkle_root"] == p["merkle_root"]
    assert (await client.get("/api/ledger/proof/TAG-0001/999", headers=fpo)).status_code == 404


async def test_public_page_badge_flips_on_tamper(app, client, fpo):
    await anchored(app, client, fpo)
    pub = (await client.get(f"/api/public/shipments/{SHIP}")).json()["ledger"]
    assert pub["verified"] is True and pub["status"] == "VERIFIED" and pub["backend"] == "local"
    assert pub["note"] and "single party" in pub["note"]  # honest about the demo ledger
    app.state.verifier._cache.clear()

    async def edit(s):
        r = (
            await s.execute(select(Record).where(Record.device_id == "TAG-0001", Record.seq == 0))
        ).scalar_one()
        r.temp_c = 1.0

    await mutate(app, edit)
    pub = (await client.get(f"/api/public/shipments/{SHIP}")).json()["ledger"]
    assert pub["verified"] is False and pub["status"] == "TAMPERED"


async def test_fleet_counts_verified_batches(app, client, fpo):
    await anchored(app, client, fpo)
    k = (await client.get("/api/fleet/overview", headers=fpo)).json()["kpis"]
    assert k["verified_batches"] == 2


async def test_ledger_outage_leaves_records_pending_then_recovers(app, client, fpo, monkeypatch):
    real = app.state.ledger.submit

    async def down(kind, payload):
        raise LedgerError("bridge down")

    monkeypatch.setattr(app.state.ledger, "submit", down)
    await feed(app, 6)
    assert (await verify(client, fpo))["status"] == "PENDING"  # nothing half-anchored
    async with app.state.db.session_factory() as s:
        assert (await s.execute(select(Batch))).first() is None
    monkeypatch.setattr(app.state.ledger, "submit", real)
    await client.post(f"/api/shipments/{SHIP}/anchor", headers=fpo)
    assert (await verify(client, fpo))["status"] == "VERIFIED"


async def test_handover_canonical_payload_is_stable():
    # guards the signed/anchored hand-over format against accidental changes
    from datetime import UTC, datetime

    h = {
        "shipment_id": "S", "stage": "FARM", "actor_username": "u", "actor_role": "fpo", "organisation": "o",
        "location": "l", "lat": None, "lon": None, "notes": "", "prev_hash": "00" * 32,
        "created_at": datetime(2026, 10, 3, 3, 20, tzinfo=UTC),
    }  # fmt: skip
    assert (
        hashlib.sha256(canonical_payload(h)).hexdigest()
        == hashlib.sha256(canonical_payload(dict(h))).hexdigest()
    )
    assert b'"ts":"2026-10-03T03:20:00.000000+00:00"' in canonical_payload(h)
