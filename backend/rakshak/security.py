"""Passwords, JWT and actor signing keys."""

from __future__ import annotations

from datetime import timedelta

import bcrypt
import jwt
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from .codec.crypto import hkdf_sha256
from .config import Settings
from .db.base import utcnow
from .db.models import Role

ALGORITHM = "HS256"


def hash_password(password: str, rounds: int = 12) -> str:
    return bcrypt.hashpw(password.encode("utf-8")[:72], bcrypt.gensalt(rounds)).decode("ascii")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8")[:72], password_hash.encode("ascii"))
    except ValueError:
        return False


def create_token(settings: Settings, username: str, role: str) -> str:
    now = utcnow()
    payload = {
        "sub": username,
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.jwt_ttl_minutes)).timestamp()),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=ALGORITHM)


def decode_token(settings: Settings, token: str) -> dict:
    """Raises ``jwt.PyJWTError`` on any problem."""
    data = jwt.decode(
        token, settings.jwt_secret, algorithms=[ALGORITHM], options={"require": ["exp", "sub"]}
    )
    if data.get("role") not in {r.value for r in Role}:
        raise jwt.InvalidTokenError("unknown role")
    return data


# --- custody signatures ---------------------------------------------------------------------
# Hand-overs are signed with an Ed25519 key per actor. The key is derived from the master key and
# the username, and signing happens server-side after the actor authenticated (documented limitation:
# a client-held key would need a mobile wallet; see docs/LIMITATIONS.md).


def actor_private_key(master_key: bytes, username: str) -> Ed25519PrivateKey:
    seed = hkdf_sha256(master_key, f"rakshak-actor-v1|{username}".encode(), 32)
    return Ed25519PrivateKey.from_private_bytes(seed)


def public_key_hex(key: Ed25519PrivateKey) -> str:
    return key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw).hex()


def verify_signature(public_key_hex_: str, message: bytes, signature_hex: str) -> bool:
    try:
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(public_key_hex_)).verify(
            bytes.fromhex(signature_hex), message
        )
        return True
    except Exception:
        return False
