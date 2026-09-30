"""Merkle trees over record hashes (RFC 6962 construction, spec §8).

    leaf(h)      = SHA-256(0x00 || h)            h = a record's 32-byte chain hash
    node(l, r)   = SHA-256(0x01 || l || r)
    MTH(D[n])    = node(MTH(D[0:k]), MTH(D[k:n]))   k = largest power of two < n
    MTH({})      = SHA-256("")

The 0x00/0x01 prefixes make a leaf indistinguishable from an inner node (no second-preimage
ambiguity) and the unbalanced split needs no duplicated leaves.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence

EMPTY_ROOT = hashlib.sha256(b"").digest()


def leaf_hash(record_hash: bytes) -> bytes:
    return hashlib.sha256(b"\x00" + record_hash).digest()


def node_hash(left: bytes, right: bytes) -> bytes:
    return hashlib.sha256(b"\x01" + left + right).digest()


def _split(n: int) -> int:
    return 1 << ((n - 1).bit_length() - 1)


def _mth(hashes: Sequence[bytes]) -> bytes:
    n = len(hashes)
    if n == 1:
        return hashes[0]
    k = _split(n)
    return node_hash(_mth(hashes[:k]), _mth(hashes[k:]))


def merkle_root(record_hashes: Sequence[bytes]) -> bytes:
    if not record_hashes:
        return EMPTY_ROOT
    return _mth([leaf_hash(h) for h in record_hashes])


def root_of_roots(roots: Sequence[bytes]) -> bytes:
    """Merkle root over batch roots (used by hand-overs); same construction."""
    return merkle_root(roots)


Proof = list[tuple[bytes, str]]  # (sibling hash, "L" | "R" = side the sibling is on)


def _path(index: int, hashes: Sequence[bytes]) -> Proof:
    n = len(hashes)
    if n == 1:
        return []
    k = _split(n)
    if index < k:
        return [*_path(index, hashes[:k]), (_mth(hashes[k:]), "R")]
    return [*_path(index - k, hashes[k:]), (_mth(hashes[:k]), "L")]


def merkle_proof(record_hashes: Sequence[bytes], index: int) -> Proof:
    """Inclusion proof for ``record_hashes[index]``."""
    if not 0 <= index < len(record_hashes):
        raise IndexError("leaf index out of range")
    return _path(index, [leaf_hash(h) for h in record_hashes])


def verify_proof(record_hash: bytes, proof: Proof, root: bytes) -> bool:
    h = leaf_hash(record_hash)
    for sibling, side in proof:
        h = node_hash(h, sibling) if side == "R" else node_hash(sibling, h)
    return h == root
