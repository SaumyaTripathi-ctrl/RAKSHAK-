"""Simulated device identity + hash-chain state (what the firmware keeps in NVS), and its storage."""

from __future__ import annotations

import json
import struct
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from rakshak.codec import Record, derive_device_key, encode_frame, pack_body
from rakshak.codec import spec as S
from rakshak.codec.chain import compute_hash
from rakshak.codec.crypto import seal
from rakshak.codec.record import pack_id


class DeviceStore(Protocol):
    def load(self, device_id: str) -> dict | None: ...
    def save(self, device_id: str, state: dict) -> None: ...


class MemoryStore:
    def __init__(self) -> None:
        self.data: dict[str, dict] = {}

    def load(self, device_id: str) -> dict | None:
        return self.data.get(device_id)

    def save(self, device_id: str, state: dict) -> None:
        self.data[device_id] = dict(state)


class JsonStore:
    """Persists ``seq`` / ``prev_hash`` across restarts like NVS does (``seq`` must never be reused)."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.data: dict[str, dict] = {}
        if self.path.exists():
            try:
                self.data = json.loads(self.path.read_text(encoding="utf-8"))
            except ValueError:
                self.data = {}

    def load(self, device_id: str) -> dict | None:
        return self.data.get(device_id)

    def save(self, device_id: str, state: dict) -> None:
        self.data[device_id] = dict(state)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data), encoding="utf-8")
        tmp.replace(self.path)


class SimDevice:
    """Identity, key, persisted ``seq`` and hash-chain head of one hub or tag."""

    def __init__(
        self,
        device_id: str,
        master_key: bytes,
        store: DeviceStore,
        *,
        key_epoch: int = 0,
        resume: dict | None = None,
    ) -> None:
        self.id = device_id
        self.store = store
        state = store.load(device_id) or resume or {}
        self.key_epoch = int(state.get("key_epoch", key_epoch))
        self.key = derive_device_key(master_key, device_id, self.key_epoch)
        self.seq = int(state.get("seq", 0))
        self.prev = bytes.fromhex(state["prev_hash"]) if state.get("prev_hash") else S.GENESIS_HASH

    def _persist(self) -> None:
        self.store.save(
            self.id, {"seq": self.seq, "prev_hash": self.prev.hex(), "key_epoch": self.key_epoch}
        )

    def emit(self, build: Callable[[int], Record]) -> bytes:
        """Encrypt and chain the record built for the next ``seq``. ``seq`` is persisted *before* use."""
        seq = self.seq
        self.seq += 1
        self._persist()
        frame, rec_hash = encode_frame(build(seq), self.prev, self.key, self.key_epoch)
        self.prev = rec_hash
        self._persist()
        return frame

    def emit_forged(self, build: Callable[[int], Record]) -> bytes:
        """A *compromised device* (valid key) sends an edited record without recomputing the hash."""
        seq = self.seq
        self.seq += 1
        rec = build(seq)
        body = pack_body(rec)
        bogus = compute_hash(self.prev, b"forged-" + body)
        header = struct.pack(
            S.HEADER_FMT, S.VERSION, int(rec.TYPE), pack_id(self.id), self.key_epoch, seq
        )
        frame = header + seal(self.key, seq, header, body + self.prev + bogus)
        self.prev = bogus
        self._persist()
        return frame
