"""DEMO ONLY: replaces each signature with one made from a plain random nonce. Valid and low-S, so the network accepts it, but not the deterministic signature the vault expects."""

import secrets

from embit.psbt import PSBT
from embit.util.key import ECKey

from satchel_core.signing import (
    SECP256K1_N,
    SIGHASH_ALL,
    is_low_s,
    private_key_from_wif,
    verify_digest,
)
from satchel_core.transactions import input_sighashes


def _random_nonce(_secret: int, _z: int, extra_data=None) -> int:
    return secrets.randbelow(SECP256K1_N - 1) + 1


def resign_with_random_nonces(signed: PSBT, wifs: list[str]) -> PSBT:
    """Re-sign a core-signed PSBT, replacing every signature's nonce."""
    sighashes = input_sighashes(signed)
    wif_by_pubkey = {}
    for wif in wifs:
        wif_by_pubkey[private_key_from_wif(wif).get_public_key().sec()] = wif
    for i, scope in enumerate(signed.inputs):
        if len(scope.partial_sigs) != 1:
            raise ValueError(
                f"input {i} must have exactly one partial signature, "
                f"has {len(scope.partial_sigs)}"
            )
        public_key = next(iter(scope.partial_sigs))
        wif = wif_by_pubkey.get(public_key.sec())
        if wif is None:
            raise RuntimeError(f"no released key matches input {i}")
        eckey = ECKey()
        eckey.set(private_key_from_wif(wif).secret, True)
        der = eckey.sign_ecdsa(sighashes[i], nonce_function=_random_nonce)
        if not is_low_s(der) or not verify_digest(
            public_key.sec().hex(), sighashes[i], der
        ):
            raise RuntimeError(
                f"random-nonce signature for input {i} failed self-check"
            )
        scope.partial_sigs[public_key] = der + bytes([SIGHASH_ALL])
    return signed
