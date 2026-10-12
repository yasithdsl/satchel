"""Tests for the single honest signing function (plain RFC6979)."""

import hashlib
import secrets

import pytest
from embit import base58, ec
from embit.networks import NETWORKS

from satchel_core.signing import (
    SECP256K1_N,
    der_to_rs,
    is_low_s,
    private_key_from_wif,
    sign_digest,
    verify_digest,
)

SECP256K1_HALF_N = SECP256K1_N // 2


def wif_for(secret: int) -> str:
    return ec.PrivateKey(secret.to_bytes(32, "big")).wif(NETWORKS["regtest"])


def digest_of(message: str) -> bytes:
    return hashlib.sha256(message.encode()).digest()


RFC6979_VECTORS = [
    (
        1,
        "Satoshi Nakamoto",
        "934b1ea10a4b3c1757e2b0c017d0b6143ce3c9a7e6a4a49860d7a6ab210ee3d8",
        "2442ce9d2b916064108014783e923ec36b49743e2ffa1c4496f01a512aafd9e5",
    ),
    (
        1,
        "All those moments will be lost in time, like tears in rain. Time to die...",
        "8600dbd41e348fe5c9465ab92d23e3db8b98b873beecd930736488696438cb6b",
        "547fe64427496db33bf66019dacbf0039c04199abb0122918601db38a72cfc21",
    ),
    (
        0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364140,
        "Satoshi Nakamoto",
        "fd567d121db66e382991534ada77a6bd3106f0a1098c231e47993447cd6af2d0",
        "6b39cd0eb1bc8603e159ef5c20a5c8ad685a45b06ce9bebed3f153d10d93bed5",
    ),
    (
        0xF8B8AF8CE3C7CCA5E300D33939540C10D45CE001B8F252BFBC57BA0342904181,
        "Alan Turing",
        "7063ae83e7f62bbb171798131b4a0564b956930092b33b07b395615d9ec7e15c",
        "58dfcc1e00a35e1572f366ffe34ba0fc47db1e7189759b9fb233c5b05ab388ea",
    ),
]


@pytest.mark.parametrize("secret,message,r_hex,s_hex", RFC6979_VECTORS)
def test_rfc6979_known_answers(secret, message, r_hex, s_hex):
    """sign_digest is plain RFC6979: it must reproduce the standard vectors."""
    der = sign_digest(wif_for(secret), digest_of(message))
    r, s = der_to_rs(der)
    assert f"{r:064x}" == r_hex
    assert f"{s:064x}" == s_hex


def test_embit_default_grinds_low_r():
    """embit's sign() grinds for low-R by default; sign_digest passes
    grind=False explicitly so output stays byte-for-byte reproducible."""
    digest = digest_of("Satoshi Nakamoto")
    ground = ec.PrivateKey((1).to_bytes(32, "big")).sign(digest).serialize()
    ours = sign_digest(wif_for(1), digest)
    assert len(ground) <= 70
    assert len(ours) == 71
    assert ground != ours


def test_first_vector_has_high_bit_r():
    """Vector 1's r needs a leading 0x00 in DER, i.e. it is not low-R.

    A low-R-grinding signer would produce a different signature, so matching
    these vectors proves we do not grind.
    """
    r, _ = der_to_rs(sign_digest(wif_for(1), digest_of("Satoshi Nakamoto")))
    assert r.to_bytes(32, "big")[0] & 0x80


def test_signing_is_deterministic():
    wif = wif_for(secrets.randbelow(SECP256K1_N - 1) + 1)
    digest = secrets.token_bytes(32)
    assert sign_digest(wif, digest) == sign_digest(wif, digest)


def test_two_hundred_random_signatures_verify_and_are_low_s():
    for _ in range(200):
        key = ec.PrivateKey(secrets.token_bytes(32))
        wif = key.wif(NETWORKS["regtest"])
        digest = secrets.token_bytes(32)
        der = sign_digest(wif, digest)
        assert is_low_s(der)
        assert verify_digest(key.get_public_key().sec().hex(), digest, der)


def test_mainnet_wif_refused():
    secret = secrets.token_bytes(32)
    mainnet_wif = base58.encode_check(b"\x80" + secret + b"\x01")
    with pytest.raises(ValueError):
        private_key_from_wif(mainnet_wif)


def test_uncompressed_wif_refused():
    uncompressed = base58.encode_check(b"\xef" + secrets.token_bytes(32))
    with pytest.raises(ValueError):
        private_key_from_wif(uncompressed)


@pytest.mark.parametrize("size", [0, 16, 31, 33, 64])
def test_non_32_byte_digest_refused(size):
    with pytest.raises(ValueError):
        sign_digest(wif_for(1), secrets.token_bytes(size))
