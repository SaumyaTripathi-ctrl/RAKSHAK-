"""Rakshak record codec (spec v1): records, hash chain, AES-256-GCM frames.

Dependency-light on purpose (only ``cryptography``) so the simulator can install it alone.
"""

from .chain import ChainState, Finding, FindingKind, compute_hash, verify_chain, verify_next
from .crypto import derive_device_key, hkdf_sha256, make_nonce
from .frame import (
    DecodedFrame,
    FrameHeader,
    decode_frame,
    decode_frame_with_master,
    encode_frame,
    peek_header,
)
from .record import CodecError, Event, HubSample, Record, TagSample, pack_body, unpack_body
from .spec import EventCode, HubFlags, RecordType, TagFlags

__all__ = [
    "ChainState",
    "CodecError",
    "DecodedFrame",
    "Event",
    "EventCode",
    "Finding",
    "FindingKind",
    "FrameHeader",
    "HubFlags",
    "HubSample",
    "Record",
    "RecordType",
    "TagFlags",
    "TagSample",
    "compute_hash",
    "decode_frame",
    "decode_frame_with_master",
    "derive_device_key",
    "encode_frame",
    "hkdf_sha256",
    "make_nonce",
    "pack_body",
    "peek_header",
    "unpack_body",
    "verify_chain",
    "verify_next",
]
