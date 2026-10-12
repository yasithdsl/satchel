"""Signs PSBTs with released child keys; keys live only for one signing."""

from __future__ import annotations

import base64
from contextlib import contextmanager
from typing import Iterator

from embit.psbt import PSBT

from satchel_core.events import emit
from satchel_core.keys import parse_hardened_path
from satchel_core.payloads import MessageType, Payload
from satchel_core.signing import private_key_from_wif
from satchel_core.transactions import finalize_psbt, sign_psbt

from .random_nonce import resign_with_random_nonces


@contextmanager
def ephemeral_keys(release: Payload) -> Iterator[list[str]]:
    """Yield the released WIFs for the duration of the block.

    Keys exist only inside this block: they are never written to disk, logged,
    cached or kept in module state, and they are dropped on exit. The release
    payload's keys are cleared as well — it is consumed by a single use.
    """
    wifs: list[str] = []
    try:
        if release.type != MessageType.KEY_RELEASE:
            raise ValueError(f"expected key_release, got {release.type}")
        if release.body.get("kind") != "signing":
            raise ValueError("key_release kind is not 'signing'")
        keys = release.body.get("keys")
        if not isinstance(keys, list) or not keys or not all(
            isinstance(entry, dict) for entry in keys
        ):
            raise ValueError("key_release needs a non-empty 'keys' list")
        for entry in keys:
            path, wif = entry.get("path"), entry.get("wif")
            if not isinstance(path, str):
                raise ValueError("key entry 'path' must be a string")
            parse_hardened_path(path)
            if not isinstance(wif, str):
                raise ValueError("key entry 'wif' must be a string")
            try:
                private_key_from_wif(wif)
            except ValueError:
                raise ValueError(
                    "key entry 'wif' is not a valid regtest WIF"
                ) from None
            wifs.append(wif)
        if len(set(wifs)) != len(wifs):
            raise ValueError("duplicate keys in key_release")
        yield wifs
    finally:
        wifs.clear()
        keys = release.body.get("keys")
        if isinstance(keys, list):
            keys.clear()


def sign(
    psbt_payload: Payload, release: Payload, random_nonce: bool = False
) -> Payload:
    """Sign the PSBT with the released keys and return the raw transaction."""
    try:
        with ephemeral_keys(release) as wifs:
            if psbt_payload.type != MessageType.UNSIGNED_PSBT:
                raise ValueError(
                    f"expected unsigned_psbt, got {psbt_payload.type}"
                )
            encoded = psbt_payload.body.get("psbt")
            if not isinstance(encoded, str):
                raise ValueError("unsigned_psbt body needs a 'psbt' string")
            try:
                psbt = PSBT.parse(base64.b64decode(encoded, validate=True))
            except Exception as exc:
                raise ValueError("'psbt' is not a valid base64 PSBT") from exc
            if random_nonce:
                emit(
                    "signer",
                    "random_nonce_signing",
                    "DEMO random-nonce mode: signatures are valid but not "
                    "the deterministic ones the vault expects",
                )
            signed = sign_psbt(psbt, wifs)
            if random_nonce:
                signed = resign_with_random_nonces(signed, wifs)
            raw = finalize_psbt(signed)
            txid = psbt.tx.txid().hex()
        emit(
            "signer",
            "psbt_signed",
            f"signed transaction {txid}",
            {
                "txid": txid,
                "inputs": len(psbt.inputs),
                "nonce": "random" if random_nonce else "rfc6979",
            },
        )
        return Payload(MessageType.SIGNED_TX, {"tx": raw, "txid": txid})
    except ValueError as exc:
        emit(
            "signer",
            "sign_refused",
            f"refused to sign: {exc}",
            {"reason": str(exc)},
        )
        raise
