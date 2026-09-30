"""Merkle tree: independent re-derivation, shared vectors, proofs."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from rakshak.ledger.merkle import EMPTY_ROOT, merkle_proof, merkle_root, verify_proof

V = json.loads(
    (Path(__file__).resolve().parents[2] / "firmware/common/spec/vectors.json").read_text("utf-8")
)["merkle"]
LEAVES = [bytes.fromhex(x) for x in V["leaves"]]


def sha(*parts: bytes) -> bytes:
    return hashlib.sha256(b"".join(parts)).digest()


def L(h: bytes) -> bytes:
    return sha(b"\x00", h)


def N(a: bytes, b: bytes) -> bytes:
    return sha(b"\x01", a, b)


def test_hand_computed_small_trees():
    a, b, c, d, e = LEAVES[:5]
    assert merkle_root([]) == EMPTY_ROOT == sha()
    assert merkle_root([a]) == L(a)
    assert merkle_root([a, b]) == N(L(a), L(b))
    assert merkle_root([a, b, c]) == N(
        N(L(a), L(b)), L(c)
    )  # RFC 6962: split at k=2, no duplication
    assert merkle_root([a, b, c, d]) == N(N(L(a), L(b)), N(L(c), L(d)))
    assert merkle_root([a, b, c, d, e]) == N(N(N(L(a), L(b)), N(L(c), L(d))), L(e))


@pytest.mark.parametrize("n", sorted(int(k) for k in V["roots"]))
def test_vectors(n):
    assert merkle_root(LEAVES[:n]).hex() == V["roots"][str(n)]


def test_leaf_and_node_domains_differ():
    # A 2-leaf tree root must not equal the leaf hash of the concatenation (second-preimage guard).
    a, b = LEAVES[:2]
    assert merkle_root([a, b]) != L(a + b)


def test_order_and_content_sensitivity():
    base = merkle_root(LEAVES[:6])
    assert merkle_root(LEAVES[:6][::-1]) != base
    assert merkle_root(LEAVES[:5]) != base
    changed = [*LEAVES[:5], bytes(32)]
    assert merkle_root(changed) != base


@pytest.mark.parametrize("n", range(1, 10))
def test_every_proof_verifies(n):
    leaves = LEAVES[:n]
    root = merkle_root(leaves)
    for i in range(n):
        proof = merkle_proof(leaves, i)
        assert verify_proof(leaves[i], proof, root)
        assert not verify_proof(bytes(32), proof, root)
    with pytest.raises(IndexError):
        merkle_proof(leaves, n)


def test_shared_proof_vector():
    case = V["proof_case"]
    proof = [(bytes.fromhex(p["hash"]), p["side"]) for p in case["proof"]]
    assert proof == merkle_proof(LEAVES[: case["n"]], case["index"])
    assert verify_proof(LEAVES[case["index"]], proof, bytes.fromhex(V["roots"][str(case["n"])]))
