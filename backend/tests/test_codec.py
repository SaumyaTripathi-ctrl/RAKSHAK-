"""Codec tests: sizes, vectors (shared with the C implementation), chain verification."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from rakshak.codec import (
    ChainState,
    CodecError,
    Event,
    FindingKind,
    HubSample,
    TagSample,
    compute_hash,
    decode_frame,
    decode_frame_with_master,
    derive_device_key,
    encode_frame,
    hkdf_sha256,
    pack_body,
    peek_header,
    spec,
    unpack_body,
    verify_chain,
    verify_next,
)

ROOT = Path(__file__).resolve().parents[2]
VECTORS = json.loads((ROOT / "firmware/common/spec/vectors.json").read_text(encoding="utf-8"))
MASTER = bytes.fromhex(VECTORS["master_key"])


def test_sizes_match_spec():
    s = VECTORS["sizes"]
    assert s["tag_body"] == 50 and s["event_body"] == 50 and s["hub_body"] == 60
    assert s["header"] == 24
    assert s["tag_frame"] == 154 and s["event_frame"] == 154 and s["hub_frame"] == 164


def test_vectors_file_is_fresh():
    """The committed vectors must equal what the reference codec generates right now."""
    res = subprocess.run(
        [sys.executable, str(ROOT / "tools/gen_vectors.py"), "--check"],
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0, res.stderr


def test_hkdf_matches_rfc5869_a1():
    v = {k: bytes.fromhex(x) for k, x in VECTORS["hkdf_rfc5869_a1"].items()}
    assert hkdf_sha256(v["ikm"], v["info"], 42, v["salt"]) == v["okm"]


@pytest.mark.parametrize(
    "k", VECTORS["device_keys"], ids=lambda k: f"{k['device_id']}-e{k['key_epoch']}"
)
def test_device_keys(k):
    assert derive_device_key(MASTER, k["device_id"], k["key_epoch"]).hex() == k["key"]


def test_key_epoch_changes_key():
    assert derive_device_key(MASTER, "TAG-0001", 0) != derive_device_key(MASTER, "TAG-0001", 1)
    assert derive_device_key(MASTER, "TAG-0001", 0) != derive_device_key(MASTER, "TAG-0002", 0)


@pytest.mark.parametrize("r", VECTORS["records"], ids=lambda r: r["name"])
def test_record_vectors(r):
    frame = bytes.fromhex(r["frame"])
    hdr = peek_header(frame)
    assert hdr.key_epoch == r["key_epoch"] and hdr.seq == r["fields"]["seq"]
    key = derive_device_key(MASTER, hdr.device_id, hdr.key_epoch)
    dec = decode_frame(frame, key)
    assert dec.body.hex() == r["body"]
    assert dec.prev_hash.hex() == r["prev_hash"]
    assert dec.hash.hex() == r["hash"]
    assert dec.hash_ok
    assert pack_body(dec.record) == dec.body
    assert unpack_body(dec.body) == dec.record
    assert len(frame) == spec.FRAME_LEN[dec.record.TYPE]
    # Re-encoding is deterministic: byte-identical frame.
    again, h = encode_frame(dec.record, dec.prev_hash, key, hdr.key_epoch)
    assert again == frame and h.hex() == r["hash"]
    assert decode_frame_with_master(frame, MASTER).record == dec.record


@pytest.mark.parametrize("n", VECTORS["negative"], ids=lambda n: n["name"])
def test_negative_vectors_rejected(n):
    frame = bytes.fromhex(n["frame"])
    key = derive_device_key(MASTER, n["device_id"], n["key_epoch"])
    with pytest.raises(CodecError):
        decode_frame(frame, key)


def test_field_conversions():
    tag = TagSample("TAG-0001", "RKS-1", 7, 1000, -150, 9123, 345, 0b11, 50)
    assert tag.temp_c == -1.5 and tag.rh_pct == 91.23 and tag.ethylene_idx == 34.5
    assert tag.lid_open and tag.ts_valid
    hub = HubSample("HUB-1", "RKS-1", 0, 5, 0, 0, 12, -33_868_800, 151_209_300, 0b1110, 0, 1, 0)
    assert hub.lat == -33.8688 and hub.gps_valid and hub.fan_on and hub.ts_valid
    ev = Event("TAG-1", "RKS-1", 0, 0, 1, 300, 0, 2, 1)
    assert ev.arg32 == 300


@pytest.mark.parametrize("bad", ["", "has space", "x" * 17, "naïve", "a/b"])
def test_invalid_identifiers(bad):
    with pytest.raises(CodecError):
        pack_body(TagSample(bad, "RKS-1", 0, 0, 0, 0, 0, 0, 0))


def test_out_of_range_field_rejected():
    with pytest.raises(CodecError):
        pack_body(TagSample("TAG-1", "RKS-1", 0, 0, 40000, 0, 0, 0, 0))  # int16 overflow


def test_malformed_frames_rejected():
    key = derive_device_key(MASTER, "TAG-0001", 0)
    good = bytes.fromhex(VECTORS["records"][0]["frame"])
    for bad in (
        good[:-1],
        good + b"\x00",
        b"",
        good[:10],
        bytes([9]) + good[1:],
        good[:1] + b"\x07" + good[2:],
    ):
        with pytest.raises(CodecError):
            decode_frame(bad, key)


def test_wrong_key_rejected():
    good = bytes.fromhex(VECTORS["records"][0]["frame"])
    with pytest.raises(CodecError):
        decode_frame(good, derive_device_key(MASTER, "TAG-0002", 0))


# --- chain verification ---------------------------------------------------------------------


def _chain(n=5, start=0):
    key = derive_device_key(MASTER, "TAG-0009", 0)
    prev = spec.GENESIS_HASH
    out = []
    for i in range(start, start + n):
        rec = TagSample("TAG-0009", "RKS-1", i, 1000 + i * 60, 2500 + i, 9000, 100, 0b10, 90)
        frame, h = encode_frame(rec, prev, key, 0)
        out.append(decode_frame(frame, key))
        prev = h
    return out


def _tuples(frames):
    return [(f.record.seq, f.prev_hash, f.body, f.hash) for f in frames]


def test_clean_chain_has_no_findings():
    assert verify_chain(_tuples(_chain())) == []


def test_edited_record_detected_as_bad_hash():
    frames = _chain()
    t = list(_tuples(frames))
    seq, prev, body, h = t[2]
    body = bytearray(body)
    body[42] ^= 0x01  # change temperature bit, keep stored hash
    t[2] = (seq, prev, bytes(body), h)
    kinds = {f.kind for f in verify_chain(t)}
    assert FindingKind.BAD_HASH in kinds


def test_edited_record_with_recomputed_hash_breaks_next_link():
    frames = _chain()
    t = list(_tuples(frames))
    seq, prev, body, _ = t[2]
    body = bytearray(body)
    body[42] ^= 0x01
    t[2] = (seq, prev, bytes(body), compute_hash(prev, bytes(body)))  # attacker fixes own hash
    findings = verify_chain(t)
    assert [f.kind for f in findings] == [FindingKind.CHAIN_BREAK]
    assert findings[0].seq == 3 and findings[0].is_tamper


def test_deleted_record_detected_as_missing():
    t = _tuples(_chain())
    del t[2]
    findings = verify_chain(t)
    miss = [f for f in findings if f.kind is FindingKind.MISSING]
    assert len(miss) == 1 and miss[0].seq == 2 and miss[0].count == 1
    assert not miss[0].is_tamper  # gap is reported, but may just be undelivered


def test_leading_gap_reported():
    findings = verify_chain(_tuples(_chain(3, start=4)))
    assert (
        findings[0].kind is FindingKind.MISSING and findings[0].seq == 0 and findings[0].count == 4
    )


def test_duplicate_does_not_advance_state():
    t = _tuples(_chain(3))
    state = ChainState()
    for x in t:
        verify_next(state, *x)
    again = verify_next(state, *t[1])
    assert [f.kind for f in again] == [FindingKind.DUPLICATE]
    assert state.last_seq == 2


def test_non_genesis_first_record_with_prev_zero_ok_only_at_seq0():
    t = _tuples(_chain(2))
    # Forge a record claiming seq 0 but with a non-zero prev_hash.
    seq, _, body, _ = t[0]
    fake_prev = bytes([1]) * 32
    forged = (seq, fake_prev, body, compute_hash(fake_prev, body))
    findings = verify_chain([forged])
    assert any(f.kind is FindingKind.CHAIN_BREAK for f in findings)
