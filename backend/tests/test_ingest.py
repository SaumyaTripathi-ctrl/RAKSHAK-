"""Ingest pipeline: decrypt -> verify chain -> dedupe -> store, incl. every tamper scenario."""

from __future__ import annotations

from rakshak.codec import EventCode
from rakshak.db.models import Device, Event, OfflineSegment, Record
from sqlalchemy import select

from .helpers import T0, FakeDevice

SHIP = "RKS-26-000001"


async def events(app, kind=None):
    async with app.state.db.session_factory() as s:
        q = select(Event).order_by(Event.id)
        if kind:
            q = q.where(Event.kind == kind)
        return list((await s.execute(q)).scalars())


async def records(app, device_id):
    async with app.state.db.session_factory() as s:
        return list(
            (
                await s.execute(
                    select(Record).where(Record.device_id == device_id).order_by(Record.seq)
                )
            ).scalars()
        )


async def test_clean_stream_is_stored_and_verified(app):
    ing, tag = app.state.ingestor, FakeDevice("TAG-0001", SHIP)
    for i in range(5):
        res = await ing.ingest_frame(tag.tag(T0 + 60 * i, temp=12 + i), via_hub="HUB-0001")
        assert res.status == "stored" and not res.findings
    rows = await records(app, "TAG-0001")
    assert [r.seq for r in rows] == [0, 1, 2, 3, 4]
    assert all(r.hash_ok and r.chain_ok for r in rows)
    assert rows[2].temp_c == 14.0 and rows[0].time_utc == T0
    async with app.state.db.session_factory() as s:
        dev = await s.get(Device, "TAG-0001")
        assert dev.last_seq == 4 and dev.battery_pct == 90 and dev.last_seen_at is not None
    assert [e for e in await events(app) if e.kind != "LEDGER_ANCHORED"] == []


async def test_duplicate_delivery_is_dropped(app):
    ing, tag = app.state.ingestor, FakeDevice("TAG-0001", SHIP)
    f = tag.tag(T0)
    assert (await ing.ingest_frame(f)).status == "stored"
    assert (await ing.ingest_frame(f)).status == "duplicate"
    assert len(await records(app, "TAG-0001")) == 1


async def test_redelivery_with_different_hash_is_tamper_conflict(app):
    ing = app.state.ingestor
    a, b = FakeDevice("TAG-0001", SHIP), FakeDevice("TAG-0001", SHIP)
    assert (await ing.ingest_frame(a.tag(T0, temp=10))).stored
    res = await ing.ingest_frame(b.tag(T0, temp=30))  # same seq 0, different content
    assert res.status == "rejected"
    assert [e.kind for e in await events(app)] == ["TAMPER_CONFLICT"]
    assert len(await records(app, "TAG-0001")) == 1


async def test_deleted_records_reported_as_missing(app):
    ing, tag = app.state.ingestor, FakeDevice("TAG-0001", SHIP)
    await ing.ingest_frame(tag.tag(T0))
    tag.skip(3)  # seq 1..3 never arrive
    res = await ing.ingest_frame(tag.tag(T0 + 240))
    assert res.stored
    ev = await events(app, "MISSING_RECORDS")
    assert len(ev) == 1 and ev[0].data == {"first_seq": 1, "count": 3}


async def test_late_arrival_fills_gap_and_verifies(app):
    ing, tag = app.state.ingestor, FakeDevice("TAG-0001", SHIP)
    f0, f1, f2 = tag.tag(T0), tag.tag(T0 + 60), tag.tag(T0 + 120)
    await ing.ingest_frame(f0)
    await ing.ingest_frame(f2)  # f1 delayed
    assert len(await events(app, "MISSING_RECORDS")) == 1
    res = await ing.ingest_frame(f1)
    assert res.status == "late_filled" and not res.findings
    assert [r.seq for r in await records(app, "TAG-0001")] == [0, 1, 2]
    assert len(await events(app, "GAP_FILLED")) == 1
    assert not await events(app, "TAMPER_CHAIN_BREAK")


async def test_forged_late_record_breaks_chain(app):
    ing = app.state.ingestor
    real, fake = FakeDevice("TAG-0001", SHIP), FakeDevice("TAG-0001", SHIP)
    f0, f1, f2 = real.tag(T0), real.tag(T0 + 60), real.tag(T0 + 120)
    await ing.ingest_frame(f0)
    await ing.ingest_frame(f2)
    fake.tag(T0)
    forged = fake.tag(
        T0 + 60, temp=40
    )  # valid key, links to seq 0, but different content than real f1
    res = await ing.ingest_frame(forged)
    assert res.status == "late_filled"
    assert any(f.kind.value == "CHAIN_BREAK" for f in res.findings)
    assert await events(app, "TAMPER_CHAIN_BREAK")
    _ = f1


async def test_bad_hash_detected_and_flagged(app):
    ing, tag = app.state.ingestor, FakeDevice("TAG-0001", SHIP)
    await ing.ingest_frame(tag.tag(T0))
    res = await ing.ingest_frame(tag.tampered_body_frame(T0 + 60))
    assert res.stored  # kept for forensics...
    assert any(f.kind.value == "BAD_HASH" for f in res.findings)
    row = (await records(app, "TAG-0001"))[-1]
    assert row.hash_ok is False and row.chain_ok is False  # ...but flagged
    assert await events(app, "TAMPER_BAD_HASH")


async def test_modified_frame_fails_authentication(app):
    ing, tag = app.state.ingestor, FakeDevice("TAG-0001", SHIP)
    f = bytearray(tag.tag(T0))
    f[40] ^= 0x01
    res = await ing.ingest_frame(bytes(f))
    assert res.status == "rejected"
    assert [e.kind for e in await events(app)] == ["AUTH_FAILED"]
    assert await records(app, "TAG-0001") == []


async def test_wrong_key_or_future_epoch_rejected(app):
    ing = app.state.ingestor
    wrong = FakeDevice("TAG-0001", SHIP, master=bytes(32))
    assert (await ing.ingest_frame(wrong.tag(T0))).status == "rejected"
    future = FakeDevice("TAG-0002", SHIP, key_epoch=3)
    assert (await ing.ingest_frame(future.tag(T0))).status == "rejected"
    assert {e.kind for e in await events(app)} == {"AUTH_FAILED"}


async def test_unknown_device_and_garbage_rejected(app):
    ing = app.state.ingestor
    assert (await ing.ingest_frame(FakeDevice("TAG-9999", SHIP).tag(T0))).status == "rejected"
    assert (await ing.ingest_frame(b"garbage")).status == "rejected"
    assert [e.kind for e in await events(app)] == ["UNKNOWN_DEVICE"]


async def test_key_rotation_old_and_new_epoch_both_accepted(app):
    ing = app.state.ingestor
    old = FakeDevice("TAG-0001", SHIP, key_epoch=0)
    await ing.ingest_frame(old.tag(T0))
    async with app.state.db.session_factory() as s:
        (await s.get(Device, "TAG-0001")).key_epoch = 1
        await s.commit()
    new = FakeDevice("TAG-0001", SHIP, key_epoch=1)
    new.seq, new.prev = old.seq, old.prev  # seq and chain continue across re-provisioning
    res = await ing.ingest_frame(new.tag(T0 + 60))
    assert res.status == "stored" and not res.findings


async def test_time_rebase_after_time_sync(app):
    ing, tag = app.state.ingestor, FakeDevice("TAG-0001", SHIP)
    await ing.ingest_frame(tag.event(0, EventCode.BOOT, valid=False))
    for i in range(3):
        await ing.ingest_frame(tag.tag(60 * (i + 1), valid=False))  # monotonic 60,120,180
    # clock synced at monotonic 300 == epoch T0+300
    await ing.ingest_frame(tag.event(T0 + 300, EventCode.TIME_SYNC, 300, 0))
    rows = {r.seq: r for r in await records(app, "TAG-0001")}
    assert [rows[i].time_utc for i in (1, 2, 3)] == [T0 + 60, T0 + 120, T0 + 180]
    assert all(rows[i].time_estimated for i in (1, 2, 3))
    assert rows[4].time_utc == T0 + 300 and not rows[4].time_estimated


async def test_lid_shock_low_battery_events(app):
    ing, tag = app.state.ingestor, FakeDevice("TAG-0001", SHIP)
    await ing.ingest_frame(tag.event(T0, EventCode.LID_OPEN))
    await ing.ingest_frame(tag.event(T0 + 1, EventCode.SHOCK, 185))
    await ing.ingest_frame(tag.event(T0 + 2, EventCode.LOW_BATTERY, batt=9))
    assert [e.kind for e in await events(app)] == ["LID_OPEN", "SHOCK", "LOW_BATTERY"]
    assert (await events(app, "SHOCK"))[0].data["shock_g"] == 1.85


async def test_hub_sample_alert_transitions_and_gps(app):
    ing, hub = app.state.ingestor, FakeDevice("HUB-0001", SHIP)
    await ing.ingest_frame(hub.hub(T0, alert=0))
    await ing.ingest_frame(hub.hub(T0 + 60, alert=1, gps=False, temp=31))
    await ing.ingest_frame(hub.hub(T0 + 120, alert=2))
    await ing.ingest_frame(hub.hub(T0 + 180, alert=0))
    assert [e.kind for e in await events(app)] == ["ALERT_WARNING", "ALERT_CRITICAL", "RECOVERED"]
    rows = await records(app, "HUB-0001")
    assert rows[1].lat is None and rows[0].lat == 16.99


async def test_hub_offline_then_online_creates_segment(app):
    ing, hub = app.state.ingestor, FakeDevice("HUB-0001", SHIP)
    await ing.ingest_frame(hub.hub(T0))
    await ing.handle_hub_event("HUB-0001", {"type": "status", "online": True})
    await ing.handle_hub_event("HUB-0001", {"type": "status", "online": False})  # last-will
    async with app.state.db.session_factory() as s:
        seg = (await s.execute(select(OfflineSegment))).scalar_one()
        assert seg.start_ts == T0 and seg.end_ts is None
    await ing.handle_hub_event(
        "HUB-0001",
        {"type": "status", "online": True, "backlog": 40, "offline_since": T0 + 30, "ts": T0 + 900},
    )
    async with app.state.db.session_factory() as s:
        seg = (await s.execute(select(OfflineSegment))).scalar_one()
        assert (seg.start_ts, seg.end_ts, seg.backlog_at_end) == (T0, T0 + 900, 40)
        dev = await s.get(Device, "HUB-0001")
        assert dev.online and dev.backlog == 40
    assert [e.kind for e in await events(app)] == ["HUB_ONLINE", "HUB_OFFLINE", "HUB_ONLINE"]


async def test_frames_are_published_to_realtime(app):
    ing, tag = app.state.ingestor, FakeDevice("TAG-0001", SHIP)
    async with app.state.realtime.subscribe(SHIP) as sub:
        await ing.ingest_frame(tag.tag(T0, temp=14))
        msg = sub.queue.get_nowait()
    assert msg["type"] == "record" and msg["data"]["temp_c"] == 14.0
