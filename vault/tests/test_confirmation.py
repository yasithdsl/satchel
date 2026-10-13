"""Offline confirmation: the vault's txout proof check."""

import json
import secrets
from pathlib import Path

import pytest

from satchel_vault.confirmation import (
    InvalidProof,
    target_from_bits,
    verify_txout_proof,
)

from .proofs import build_proof, header_for, sha256d

VECTORS = json.loads(
    (Path(__file__).parent / "fixtures" / "txout_proofs.json").read_text()
)


def txids(n: int) -> list[str]:
    return [secrets.token_hex(32) for _ in range(n)]


@pytest.mark.parametrize("vector", VECTORS, ids=lambda v: v["txid"][:8])
def test_real_bitcoin_core_proofs_verify(vector):
    assert verify_txout_proof(vector["proof"], vector["txid"]) == {
        "block_hash": vector["block_hash"]
    }


def test_real_proof_does_not_prove_another_transaction():
    first, other = VECTORS[0], VECTORS[-1]
    with pytest.raises(InvalidProof, match="does not include"):
        verify_txout_proof(first["proof"], other["txid"])


@pytest.mark.parametrize("count", [1, 2, 3, 5, 8, 9])
def test_built_proofs_verify_for_every_position(count):
    ids = txids(count)
    for match in range(count):
        verify_txout_proof(build_proof(ids, match), ids[match])
        others = [t for i, t in enumerate(ids) if i != match]
        for other in others:
            with pytest.raises(InvalidProof):
                verify_txout_proof(build_proof(ids, match), other)


def test_tampered_tree_hash_breaks_the_root():
    ids = txids(5)
    proof = bytearray(bytes.fromhex(build_proof(ids, 2)))
    proof[80 + 4 + 1 + 3] ^= 0x01  # inside the first tree hash
    with pytest.raises(InvalidProof):
        verify_txout_proof(proof.hex(), ids[2])


def test_header_for_another_root_is_rejected():
    ids = txids(4)
    wrong_header = header_for(sha256d(b"some other block"))
    with pytest.raises(InvalidProof, match="merkle root"):
        verify_txout_proof(build_proof(ids, 1, header=wrong_header), ids[1])


def test_header_without_work_is_rejected():
    ids = txids(2)
    hard_bits = 0x1D00FFFF  # mainnet difficulty 1: a random header misses it
    header = bytearray(header_for(sha256d(b"x")))
    header[72:76] = hard_bits.to_bytes(4, "little")
    with pytest.raises(InvalidProof, match="proof of work"):
        verify_txout_proof(build_proof(ids, 0, header=bytes(header)), ids[0])


def test_target_out_of_range_is_rejected():
    ids = txids(1)
    header = bytearray(header_for(bytes.fromhex(ids[0])[::-1]))
    header[72:76] = (0x22FFFFFF & ~0x00800000).to_bytes(4, "little")
    with pytest.raises(InvalidProof, match="target"):
        verify_txout_proof(build_proof(ids, 0, header=bytes(header)), ids[0])
    assert target_from_bits(0x207FFFFF) < 2**255


def test_duplicate_branch_is_rejected():
    # CVE-2012-2459: a tree whose two halves are equal can stand for two blocks.
    leaf = bytes.fromhex(secrets.token_hex(32))
    header = header_for(sha256d(leaf + leaf))
    proof = (
        header
        + (2).to_bytes(4, "little")
        + bytes([2])
        + leaf
        + leaf
        + bytes([1])
        + bytes([0b011])
    )
    with pytest.raises(InvalidProof, match="duplicate"):
        verify_txout_proof(proof.hex(), leaf[::-1].hex())


@pytest.mark.parametrize(
    "mangle",
    [
        lambda p: p[:-2],  # truncated
        lambda p: p + "00",  # trailing bytes
        lambda p: p[:160] + "00000000" + p[168:],  # zero transactions
        lambda p: "zz" + p[2:],  # not hex
    ],
)
def test_malformed_proofs_are_rejected(mangle):
    ids = txids(3)
    with pytest.raises(InvalidProof):
        verify_txout_proof(mangle(build_proof(ids, 1)), ids[1])


def test_txid_must_be_lowercase_hex():
    ids = txids(1)
    with pytest.raises(InvalidProof, match="txid"):
        verify_txout_proof(build_proof(ids, 0), ids[0].upper())
