"""Frames: the unit stored in flash, sent over BLE and published over MQTT."""

from __future__ import annotations

import struct
from dataclasses import dataclass

from . import spec
from .chain import compute_hash
from .crypto import derive_device_key, open_, seal
from .record import CodecError, Record, pack_body, pack_id, unpack_body, unpack_id
from .spec import RecordType


@dataclass(frozen=True)
class FrameHeader:
    version: int
    type: RecordType
    device_id: str
    key_epoch: int
    seq: int


@dataclass(frozen=True)
class DecodedFrame:
    header: FrameHeader
    record: Record
    body: bytes
    prev_hash: bytes
    hash: bytes  # as stored by the device (not yet verified)

    @property
    def hash_ok(self) -> bool:
        """True if the stored hash equals SHA-256(prev_hash || body)."""
        return compute_hash(self.prev_hash, self.body) == self.hash


def peek_header(frame: bytes) -> FrameHeader:
    """Parse the unencrypted header (the hub uses this to ACK by seq without any key)."""
    if len(frame) < spec.HEADER_LEN:
        raise CodecError("frame shorter than header")
    version, rtype, dev, epoch, seq = struct.unpack_from(spec.HEADER_FMT, frame)
    if version != spec.VERSION:
        raise CodecError(f"unsupported version {version}")
    try:
        rtype_e = RecordType(rtype)
    except ValueError as exc:
        raise CodecError(f"unknown record type {rtype}") from exc
    if len(frame) != spec.FRAME_LEN[rtype_e]:
        raise CodecError(f"bad frame length {len(frame)} for type {rtype}")
    return FrameHeader(version, rtype_e, unpack_id(dev), epoch, seq)


def encode_frame(
    rec: Record, prev_hash: bytes, device_key: bytes, key_epoch: int
) -> tuple[bytes, bytes]:
    """Encrypt one record. Returns ``(frame, record_hash)``."""
    if len(prev_hash) != spec.HASH_LEN:
        raise CodecError("prev_hash must be 32 bytes")
    body = pack_body(rec)
    rec_hash = compute_hash(prev_hash, body)
    header = struct.pack(
        spec.HEADER_FMT, spec.VERSION, int(rec.TYPE), pack_id(rec.device_id), key_epoch, rec.seq
    )
    sealed = seal(device_key, rec.seq, header, body + prev_hash + rec_hash)
    frame = header + sealed
    assert len(frame) == spec.FRAME_LEN[rec.TYPE]
    return frame, rec_hash


def decode_frame(frame: bytes, device_key: bytes) -> DecodedFrame:
    header = peek_header(frame)
    plain = open_(device_key, header.seq, frame[: spec.HEADER_LEN], frame[spec.HEADER_LEN :])
    blen = spec.BODY_LEN[header.type]
    body, prev_hash, rec_hash = plain[:blen], plain[blen : blen + 32], plain[blen + 32 :]
    rec = unpack_body(body)
    if (rec.TYPE, rec.device_id, rec.seq) != (header.type, header.device_id, header.seq):
        raise CodecError("body does not match frame header")
    return DecodedFrame(header, rec, body, prev_hash, rec_hash)


def decode_frame_with_master(frame: bytes, master_key: bytes) -> DecodedFrame:
    """Derive the device key from the header and decode."""
    header = peek_header(frame)
    return decode_frame(frame, derive_device_key(master_key, header.device_id, header.key_epoch))
