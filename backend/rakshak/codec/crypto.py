"""Key derivation and AES-256-GCM helpers (spec v1)."""

from __future__ import annotations

import hashlib
import hmac

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from . import spec
from .record import CodecError


def hkdf_sha256(ikm: bytes, info: bytes, length: int = 32, salt: bytes | None = None) -> bytes:
    """RFC 5869 HKDF-SHA256 (no salt => HashLen zero bytes, as mbedtls_hkdf with NULL salt)."""
    if length > 255 * spec.HASH_LEN:
        raise CodecError("hkdf length too large")
    prk = hmac.new(salt or bytes(spec.HASH_LEN), ikm, hashlib.sha256).digest()
    okm = b""
    block = b""
    counter = 1
    while len(okm) < length:
        block = hmac.new(prk, block + info + bytes([counter]), hashlib.sha256).digest()
        okm += block
        counter += 1
    return okm[:length]


def derive_device_key(master_key: bytes, device_id: str, key_epoch: int) -> bytes:
    """``HKDF-SHA256(master, info="rakshak-v1|<device_id>|<key_epoch>")`` -> 32-byte key."""
    if len(master_key) != spec.KEY_LEN:
        raise CodecError("master key must be 32 bytes")
    if not 0 <= key_epoch <= 0xFFFF:
        raise CodecError("key_epoch out of range")
    info = spec.HKDF_INFO_PREFIX + f"{device_id}|{key_epoch}".encode("ascii")
    return hkdf_sha256(master_key, info, spec.KEY_LEN)


def make_nonce(seq: int) -> bytes:
    """``0x00 x 8 || seq`` with seq as u32 little-endian (like every other multi-byte field)."""
    return bytes(8) + seq.to_bytes(4, "little")


def seal(key: bytes, seq: int, aad: bytes, plaintext: bytes) -> bytes:
    """Returns ``ciphertext || tag`` (16-byte tag)."""
    return AESGCM(key).encrypt(make_nonce(seq), plaintext, aad)


def open_(key: bytes, seq: int, aad: bytes, ciphertext_and_tag: bytes) -> bytes:
    try:
        return AESGCM(key).decrypt(make_nonce(seq), ciphertext_and_tag, aad)
    except InvalidTag as exc:
        raise CodecError("authentication failed (bad key, key_epoch or modified frame)") from exc
