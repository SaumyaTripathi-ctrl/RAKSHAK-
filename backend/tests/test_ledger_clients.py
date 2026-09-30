"""Ledger clients: local hash-linked file and the Fabric HTTP bridge client (mocked transport)."""

from __future__ import annotations

import json

import httpx
import pytest
from rakshak.ledger.client import FabricLedger, LedgerError, LocalLedger, make_ledger


async def test_local_ledger_append_get_list(tmp_path):
    led = LocalLedger(tmp_path / "l.jsonl")
    r1 = await led.submit("BATCH", {"shipment_id": "S1", "merkle_root": "aa"})
    r2 = await led.submit("HANDOVER", {"shipment_id": "S1", "stage": "FARM"})
    assert (r1, r2) == ("local:1", "local:2")  # 0 is the genesis entry
    e = await led.get(r1)
    assert e.kind == "BATCH" and e.payload["merkle_root"] == "aa"
    assert [x.ref for x in await led.list(10)] == ["local:2", "local:1", "local:0"]
    assert (await led.get("local:99")) is None and (await led.get("bogus")) is None
    integ = await led.integrity()
    assert integ.ok and integ.entries == 3
    assert not led.decentralised


async def test_local_ledger_survives_restart(tmp_path):
    path = tmp_path / "l.jsonl"
    await LocalLedger(path).submit("BATCH", {"a": 1})
    led2 = LocalLedger(path)
    assert await led2.submit("BATCH", {"a": 2}) == "local:2"
    assert (await led2.integrity()).ok


def _lines(path):
    return path.read_text().splitlines()


async def test_local_ledger_detects_edit_deletion_and_reorder(tmp_path):
    path = tmp_path / "l.jsonl"
    led = LocalLedger(path)
    for i in range(4):
        await led.submit("BATCH", {"i": i})
    good = _lines(path)

    edited = [*good]
    row = json.loads(edited[2])
    row["payload"]["i"] = 999
    edited[2] = json.dumps(row, sort_keys=True, separators=(",", ":"))
    path.write_text("\n".join(edited) + "\n")
    integ = await led.integrity()
    assert not integ.ok and "entry 2" in integ.problem and "hash" in integ.problem

    path.write_text("\n".join(good[:2] + good[3:]) + "\n")  # delete entry 2
    assert not (await led.integrity()).ok

    path.write_text("\n".join([good[0], good[2], good[1], good[3]]) + "\n")  # reorder
    assert not (await led.integrity()).ok

    path.write_text("\n".join(good) + "\n")  # restored
    assert (await led.integrity()).ok


def fabric(handler) -> FabricLedger:
    return FabricLedger("http://bridge", transport=httpx.MockTransport(handler))


async def test_fabric_client_contract():
    store: dict[str, dict] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        path = req.url.path
        if req.method == "POST" and path == "/entries":
            body = json.loads(req.content)
            tx = f"tx{len(store) + 1}"
            store[tx] = {"txId": tx, "kind": body["kind"], "payload": body["payload"], "ts": 1}
            return httpx.Response(200, json={"txId": tx})
        if req.method == "GET" and path.startswith("/entries/"):
            tx = path.rsplit("/", 1)[1]
            return httpx.Response(200, json=store[tx]) if tx in store else httpx.Response(404)
        if req.method == "GET" and path == "/entries":
            return httpx.Response(200, json={"entries": list(store.values())})
        if path == "/health":
            return httpx.Response(200, json={"ok": True, "entries": len(store)})
        return httpx.Response(500)

    led = fabric(handler)
    ref = await led.submit("BATCH", {"merkle_root": "ab"})
    assert ref == "fabric:tx1"
    assert (await led.get(ref)).payload == {"merkle_root": "ab"}
    assert await led.get("fabric:nope") is None and await led.get("local:1") is None
    assert len(await led.list()) == 1
    assert (await led.integrity()).ok and led.decentralised


async def test_fabric_client_errors_are_ledger_errors():
    led = fabric(lambda req: httpx.Response(503))
    with pytest.raises(LedgerError):
        await led.submit("BATCH", {})
    assert not (await led.integrity()).ok


def test_factory(tmp_path):
    assert make_ledger("local", path=str(tmp_path / "x.jsonl")).name == "local"
    assert make_ledger("fabric", path="", bridge_url="http://x").name == "fabric"
    with pytest.raises(ValueError):
        make_ledger("fabric", path="")
    with pytest.raises(ValueError):
        make_ledger("nope", path="")
