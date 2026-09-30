"""SHA-256 hash chain and chain verification (spec v1)."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

from . import spec


def compute_hash(prev_hash: bytes, body: bytes) -> bytes:
    """``hash = SHA-256(prev_hash || body)``."""
    return hashlib.sha256(prev_hash + body).digest()


class FindingKind(StrEnum):
    BAD_HASH = "BAD_HASH"  # stored hash != SHA-256(prev_hash || body): record content altered
    CHAIN_BREAK = "CHAIN_BREAK"  # prev_hash does not link to previous record: edit or insertion
    MISSING = "MISSING"  # seq gap: records deleted or not yet delivered
    DUPLICATE = "DUPLICATE"  # seq already seen: harmless redelivery (QoS 1) unless hashes differ


@dataclass(frozen=True)
class Finding:
    kind: FindingKind
    seq: int  # first seq affected
    count: int = 1  # number of records affected (MISSING)

    @property
    def is_tamper(self) -> bool:
        return self.kind in (FindingKind.BAD_HASH, FindingKind.CHAIN_BREAK)


@dataclass
class ChainState:
    """Verifier state for one device."""

    last_seq: int | None = None
    last_hash: bytes = spec.GENESIS_HASH


def verify_next(
    state: ChainState, seq: int, prev_hash: bytes, body: bytes, stored_hash: bytes
) -> list[Finding]:
    """Verify one record against ``state`` and advance it.

    Records must be fed in arrival order. A seq at or below ``state.last_seq`` is reported as
    DUPLICATE and does not advance the state; the caller decides (by comparing with the hash it
    stored for that seq) whether the redelivery is identical or a forgery.
    """
    findings: list[Finding] = []
    if compute_hash(prev_hash, body) != stored_hash:
        findings.append(Finding(FindingKind.BAD_HASH, seq))

    if state.last_seq is not None and seq <= state.last_seq:
        return [*findings, Finding(FindingKind.DUPLICATE, seq)]

    expected = 0 if state.last_seq is None else state.last_seq + 1
    if seq > expected:
        findings.append(Finding(FindingKind.MISSING, expected, seq - expected))
    elif prev_hash != state.last_hash:
        findings.append(Finding(FindingKind.CHAIN_BREAK, seq))

    state.last_seq = seq
    state.last_hash = stored_hash
    return findings


def verify_chain(
    records: Iterable[tuple[int, bytes, bytes, bytes]], state: ChainState | None = None
) -> list[Finding]:
    """Verify ``(seq, prev_hash, body, stored_hash)`` tuples in order."""
    state = state or ChainState()
    out: list[Finding] = []
    for seq, prev, body, stored in records:
        out.extend(verify_next(state, seq, prev, body, stored))
    return out
