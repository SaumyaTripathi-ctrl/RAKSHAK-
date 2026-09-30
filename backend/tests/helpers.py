"""Test helpers: a scriptable fake device that emits real encrypted, chained frames."""

from __future__ import annotations

from rakshak.codec import (
    Event,
    HubSample,
    TagSample,
    derive_device_key,
    encode_frame,
    pack_body,
)
from rakshak.codec import spec as S
from rakshak.codec.chain import compute_hash

MASTER = bytes(range(32))
T0 = 1_791_000_000


class FakeDevice:
    def __init__(
        self, device_id: str, shipment_id: str, *, key_epoch: int = 0, master: bytes = MASTER
    ):
        self.id, self.shipment_id, self.key_epoch = device_id, shipment_id, key_epoch
        self.key = derive_device_key(master, device_id, key_epoch)
        self.seq = 0
        self.prev = S.GENESIS_HASH

    def _emit(self, rec, *, corrupt_hash: bool = False, advance: bool = True) -> bytes:
        frame, h = encode_frame(rec, self.prev, self.key, self.key_epoch)
        if advance:
            self.prev = h
            self.seq += 1
        return frame

    def tag(
        self,
        t: int,
        temp: float = 12.0,
        rh: float = 88.0,
        eth: float = 10.0,
        *,
        lid=False,
        valid=True,
        batt=90,
    ):
        flags = (S.TagFlags.TS_VALID if valid else 0) | (S.TagFlags.LID_OPEN if lid else 0)
        rec = TagSample(
            self.id,
            self.shipment_id,
            self.seq,
            t,
            round(temp * 100),
            round(rh * 100),
            round(eth * 10),
            int(flags),
            batt,
        )
        return self._emit(rec)

    def hub(
        self,
        t: int,
        temp=25.0,
        rh=70.0,
        shock=0.0,
        lat=16.99,
        lon=73.3,
        *,
        gps=True,
        flap=0,
        fan=False,
        alert=0,
        batt=90,
    ):
        flags = (
            S.HubFlags.TS_VALID
            | (S.HubFlags.GPS_VALID if gps else 0)
            | (S.HubFlags.FAN_ON if fan else 0)
        )
        rec = HubSample(
            self.id,
            self.shipment_id,
            self.seq,
            t,
            round(temp * 100),
            round(rh * 100),
            round(shock * 100),
            round(lat * 1e6),
            round(lon * 1e6),
            int(flags),
            flap,
            batt,
            alert,
        )
        return self._emit(rec)

    def event(self, t: int, code: int, arg0: int = 0, arg1: int = 0, *, valid=True, batt=90):
        rec = Event(
            self.id,
            self.shipment_id,
            self.seq,
            t,
            code,
            arg0,
            arg1,
            int(S.TagFlags.TS_VALID) if valid else 0,
            batt,
        )
        return self._emit(rec)

    def tampered_body_frame(self, t: int, temp: float = 99.0) -> bytes:
        """Compromised-device forgery: valid key, edited body, but the OLD hash (not recomputed)."""
        rec = TagSample(self.id, self.shipment_id, self.seq, t, round(temp * 100), 8800, 100, 2, 90)
        body = pack_body(rec)
        bogus_hash = compute_hash(self.prev, b"something else entirely....................")
        # Build a frame by hand: seal body||prev||bogus_hash.
        import struct

        from rakshak.codec.crypto import seal
        from rakshak.codec.record import pack_id

        header = struct.pack(
            S.HEADER_FMT, S.VERSION, int(rec.TYPE), pack_id(self.id), self.key_epoch, self.seq
        )
        frame = header + seal(self.key, self.seq, header, body + self.prev + bogus_hash)
        self.prev, self.seq = bogus_hash, self.seq + 1
        return frame

    def skip(self, n: int = 1) -> None:
        """Simulate records the attacker deleted: device emitted them but they never arrive."""
        for _ in range(n):
            self.tag(T0)  # produced and discarded
