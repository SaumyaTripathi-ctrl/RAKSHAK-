"""Ledger clients. ``LedgerClient`` is the only thing the rest of the backend depends on.

* ``LocalLedger``  - append-only, hash-linked JSONL file. Default; works offline; single party.
* ``FabricLedger`` - Hyperledger Fabric through a small HTTP bridge (``ledger/fabric/bridge``).
                      Optional (``RAKSHAK_LEDGER_BACKEND=fabric``). See ledger/README.md.

Entry kinds:  GENESIS | BATCH | HANDOVER
  BATCH    payload: shipment_id, device_id, batch_id, first_seq, last_seq, leaf_count, merkle_root, stage, ts
  HANDOVER payload: shipment_id, stage, handover_hash, prev_hash, signature, public_key,
                    batches_root, batch_count, ts
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

ZERO = "00" * 32


@dataclass(frozen=True)
class LedgerEntry:
    ref: str
    kind: str
    payload: dict[str, Any]
    ts: int
    prev_hash: str
    hash: str


@dataclass(frozen=True)
class LedgerIntegrity:
    ok: bool
    entries: int
    problem: str = ""


class LedgerError(RuntimeError):
    pass


class LedgerClient(ABC):
    name: str

    @abstractmethod
    async def submit(self, kind: str, payload: dict[str, Any]) -> str:
        """Append an entry; returns its reference (``local:<n>`` / ``fabric:<txid>``)."""

    @abstractmethod
    async def get(self, ref: str) -> LedgerEntry | None: ...

    @abstractmethod
    async def list(self, limit: int = 100, offset: int = 0) -> list[LedgerEntry]:
        """Newest first."""

    @abstractmethod
    async def integrity(self) -> LedgerIntegrity:
        """Is the ledger's own history intact?"""

    @property
    def decentralised(self) -> bool:
        return False


def _canonical(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )


def _entry_hash(index: int, ts: int, kind: str, payload: dict, prev_hash: str) -> str:
    return hashlib.sha256(
        _canonical(
            {"index": index, "ts": ts, "kind": kind, "payload": payload, "prev_hash": prev_hash}
        )
    ).hexdigest()


class LocalLedger(LedgerClient):
    """Append-only hash-linked ledger stored as JSON lines.

    Tamper-evident (editing or deleting any line breaks every later link) but *not* decentralised:
    whoever controls the file can rewrite it wholesale. That is what Fabric peers owned by different
    parties add. Used for demos and offline development.
    """

    name = "local"

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._lock = asyncio.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _read_all(self) -> list[dict]:
        if not self.path.exists():
            return []
        with self.path.open("r", encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]

    def _append(self, row: dict) -> None:
        with self.path.open("a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
            f.flush()
            os.fsync(f.fileno())

    @staticmethod
    def _to_entry(row: dict) -> LedgerEntry:
        return LedgerEntry(
            f"local:{row['index']}",
            row["kind"],
            row["payload"],
            row["ts"],
            row["prev_hash"],
            row["hash"],
        )

    async def submit(self, kind: str, payload: dict[str, Any]) -> str:
        async with self._lock:
            rows = self._read_all()
            if not rows:  # genesis
                g_payload = {
                    "network": "rakshak-local",
                    "note": "single-party demo ledger; not decentralised",
                }
                ts = int(time.time())
                self._append(
                    {
                        "index": 0,
                        "ts": ts,
                        "kind": "GENESIS",
                        "payload": g_payload,
                        "prev_hash": ZERO,
                        "hash": _entry_hash(0, ts, "GENESIS", g_payload, ZERO),
                    }
                )
                rows = self._read_all()
            index, prev = len(rows), rows[-1]["hash"]
            ts = int(time.time())
            self._append(
                {
                    "index": index,
                    "ts": ts,
                    "kind": kind,
                    "payload": payload,
                    "prev_hash": prev,
                    "hash": _entry_hash(index, ts, kind, payload, prev),
                }
            )
            return f"local:{index}"

    async def get(self, ref: str) -> LedgerEntry | None:
        if not ref.startswith("local:"):
            return None
        try:
            idx = int(ref.split(":", 1)[1])
        except ValueError:
            return None
        async with self._lock:
            rows = self._read_all()
        return self._to_entry(rows[idx]) if 0 <= idx < len(rows) else None

    async def list(self, limit: int = 100, offset: int = 0) -> list[LedgerEntry]:
        async with self._lock:
            rows = self._read_all()
        rows.reverse()
        return [self._to_entry(r) for r in rows[offset : offset + limit]]

    async def integrity(self) -> LedgerIntegrity:
        async with self._lock:
            try:
                rows = self._read_all()
            except (ValueError, OSError) as exc:
                return LedgerIntegrity(False, 0, f"ledger file unreadable: {exc}")
        prev = ZERO
        for i, r in enumerate(rows):
            if r.get("index") != i:
                return LedgerIntegrity(
                    False,
                    len(rows),
                    f"entry {i}: index {r.get('index')} (entry deleted or reordered)",
                )
            if r.get("prev_hash") != prev:
                return LedgerIntegrity(False, len(rows), f"entry {i}: previous-hash link broken")
            if r.get("hash") != _entry_hash(i, r["ts"], r["kind"], r["payload"], r["prev_hash"]):
                return LedgerIntegrity(
                    False, len(rows), f"entry {i}: content does not match its hash"
                )
            prev = r["hash"]
        return LedgerIntegrity(True, len(rows))


class FabricLedger(LedgerClient):
    """Hyperledger Fabric via the HTTP bridge in ``ledger/fabric/bridge`` (Node + fabric-gateway).

    EXPERIMENTAL: the bridge and chaincode are covered by unit tests and a mocked client test; they have
    not been run against a live Fabric network in this repository's CI (Fabric needs ~2 GB of images).
    """

    name = "fabric"

    def __init__(
        self,
        bridge_url: str,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = 15.0,
    ):
        self._http = httpx.AsyncClient(
            base_url=bridge_url.rstrip("/"), transport=transport, timeout=timeout
        )

    @property
    def decentralised(self) -> bool:
        return True

    async def _call(self, method: str, url: str, **kw) -> Any:
        try:
            r = await self._http.request(method, url, **kw)
            r.raise_for_status()
            return r.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise LedgerError(f"fabric bridge error: {exc}") from exc

    @staticmethod
    def _entry(d: dict) -> LedgerEntry:
        return LedgerEntry(
            f"fabric:{d['txId']}",
            d["kind"],
            d["payload"],
            d["ts"],
            d.get("prevHash", ""),
            d.get("hash", d["txId"]),
        )

    async def submit(self, kind: str, payload: dict[str, Any]) -> str:
        d = await self._call("POST", "/entries", json={"kind": kind, "payload": payload})
        return f"fabric:{d['txId']}"

    async def get(self, ref: str) -> LedgerEntry | None:
        if not ref.startswith("fabric:"):
            return None
        try:
            r = await self._http.get(f"/entries/{ref.split(':', 1)[1]}")
            if r.status_code == 404:
                return None
            r.raise_for_status()
            return self._entry(r.json())
        except (httpx.HTTPError, ValueError) as exc:
            raise LedgerError(f"fabric bridge error: {exc}") from exc

    async def list(self, limit: int = 100, offset: int = 0) -> list[LedgerEntry]:
        d = await self._call("GET", "/entries", params={"limit": limit, "offset": offset})
        return [self._entry(x) for x in d["entries"]]

    async def integrity(self) -> LedgerIntegrity:
        try:
            d = await self._call("GET", "/health")
        except LedgerError as exc:
            return LedgerIntegrity(False, 0, str(exc))
        return LedgerIntegrity(bool(d.get("ok")), int(d.get("entries", 0)), d.get("problem", ""))


def make_ledger(backend: str, *, path: str, bridge_url: str | None = None) -> LedgerClient:
    if backend == "local":
        return LocalLedger(path)
    if backend == "fabric":
        if not bridge_url:
            raise ValueError("RAKSHAK_FABRIC_BRIDGE_URL is required for the fabric ledger backend")
        return FabricLedger(bridge_url)
    raise ValueError(f"unknown ledger backend {backend!r}")
