"""PSBT construction, signing and witness finalization for P2WPKH spends."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Iterable

from embit import ec, script
from embit.psbt import DerivationPath, PSBT
from embit.transaction import Transaction, TransactionInput, TransactionOutput, Witness

from .keys import HARDENED, parse_hardened_path
from .signing import SIGHASH_ALL, private_key_from_wif, sign_digest

DUST_LIMIT_SATS = 330


@dataclass(frozen=True)
class SpendInput:
    txid: str
    vout: int
    amount_sats: int
    public_key: str
    path: str | None = None


@dataclass(frozen=True)
class Output:
    address: str
    amount_sats: int
    path: str | None = None
    public_key: str | None = None


@dataclass(frozen=True)
class InputSignature:
    index: int
    public_key: str
    signature: bytes
    sighash_type: int
    sighash: bytes


def _check_amount(value: int, what: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{what} must be a positive integer, got {value!r}")


def _check_public_key(public_key: str) -> bytes:
    sec = bytes.fromhex(public_key)
    if len(sec) != 33 or sec[0] not in (0x02, 0x03):
        raise ValueError(f"public key must be 33-byte compressed SEC: {public_key!r}")
    try:
        ec.PublicKey.parse(sec)
    except ValueError as exc:
        raise ValueError(f"invalid public key: {public_key!r}") from exc
    return sec


def _regtest_script(address: str) -> script.Script:
    if not address.startswith("bcrt1"):
        raise ValueError(f"not a regtest address: {address!r}")
    try:
        return script.address_to_scriptpubkey(address)
    except ValueError as exc:
        raise ValueError(f"invalid address: {address!r}") from exc


def _check_fingerprint(fingerprint: str | None) -> bytes:
    if not isinstance(fingerprint, str) or not re.fullmatch(
        r"[0-9a-fA-F]{8}", fingerprint
    ):
        raise ValueError(
            f"fingerprint must be 8 hex chars, got {fingerprint!r}"
        )
    return bytes.fromhex(fingerprint)


def build_psbt(
    inputs: Iterable[SpendInput],
    outputs: Iterable[Output],
    change: Output | None = None,
    fingerprint: str | None = None,
) -> PSBT:
    inputs = list(inputs)
    outputs = list(outputs) + ([change] if change is not None else [])
    if not inputs:
        raise ValueError("at least one input is required")
    if not outputs:
        raise ValueError("at least one output is required")
    master_fingerprint = (
        _check_fingerprint(fingerprint)
        if any(spend.path is not None for spend in inputs)
        or any(output.path is not None for output in outputs)
        else None
    )
    seen = set()
    vin = []
    total_in = 0
    for i, spend in enumerate(inputs):
        if not isinstance(spend.txid, str) or not re.fullmatch(
            r"[0-9a-fA-F]{64}", spend.txid
        ):
            raise ValueError(f"input {i} txid must be 64 hex chars, got {spend.txid!r}")
        if isinstance(spend.vout, bool) or not isinstance(spend.vout, int) or spend.vout < 0:
            raise ValueError(f"input {i} vout must be a non-negative integer, got {spend.vout!r}")
        if (spend.txid, spend.vout) in seen:
            raise ValueError(f"duplicate input {spend.txid}:{spend.vout}")
        seen.add((spend.txid, spend.vout))
        _check_amount(spend.amount_sats, f"input {i} amount_sats")
        _check_public_key(spend.public_key)
        vin.append(
            TransactionInput(
                bytes.fromhex(spend.txid), spend.vout, sequence=0xFFFFFFFD
            )
        )
        total_in += spend.amount_sats
    vout = []
    total_out = 0
    output_derivations: dict[int, bytes] = {}
    for i, output in enumerate(outputs):
        _check_amount(output.amount_sats, f"output {i} amount_sats")
        vout.append(TransactionOutput(output.amount_sats, _regtest_script(output.address)))
        total_out += output.amount_sats
        if output.path is not None:
            if output.public_key is None:
                raise ValueError(
                    f"output {i} has a derivation path but no public_key"
                )
            output_derivations[i] = _check_public_key(output.public_key)
            parse_hardened_path(output.path)
        elif output.public_key is not None:
            raise ValueError(
                f"output {i} has a public_key but no derivation path"
            )
    fee = total_in - total_out
    if fee <= 0:
        raise ValueError(f"fee must be positive, got {fee}")
    tx = Transaction(version=2, vin=vin, vout=vout, locktime=0)
    psbt = PSBT(tx)
    for i, spend in enumerate(inputs):
        public_key = ec.PublicKey.parse(bytes.fromhex(spend.public_key))
        psbt.inputs[i].witness_utxo = TransactionOutput(
            spend.amount_sats, script.p2wpkh(public_key)
        )
        if spend.path is not None:
            psbt.inputs[i].bip32_derivations[public_key] = DerivationPath(
                master_fingerprint, parse_hardened_path(spend.path)
            )
    for i, public_key_sec in output_derivations.items():
        public_key = ec.PublicKey.parse(public_key_sec)
        psbt.outputs[i].bip32_derivations[public_key] = DerivationPath(
            master_fingerprint, parse_hardened_path(outputs[i].path)
        )
    return psbt


def estimate_vsize(n_p2wpkh_inputs: int, output_addresses: list[str]) -> int:
    """Upper-bound virtual size: 68 vB per P2WPKH input, output size from the
    destination script length (8 amount + 1 varint + script)."""
    vbytes = 10.5 + 68 * n_p2wpkh_inputs
    for address in output_addresses:
        vbytes += 9 + len(_regtest_script(address).data)
    return math.ceil(vbytes)


def input_derivation(psbt: PSBT, i: int) -> tuple[str, str, str] | None:
    """Return (pubkey hex, fingerprint hex, "m/…" path) for a PSBT input."""
    derivations = psbt.inputs[i].bip32_derivations
    if not derivations:
        return None
    if len(derivations) != 1:
        raise ValueError(
            f"input {i} has {len(derivations)} derivations, expected one"
        )
    public_key, deriv = next(iter(derivations.items()))
    parts = [
        f"{index & ~HARDENED}'" if index & HARDENED else str(index)
        for index in deriv.derivation
    ]
    return public_key.sec().hex(), deriv.fingerprint.hex(), "m/" + "/".join(parts)


def output_derivation(psbt: PSBT, i: int) -> tuple[str, str, str] | None:
    """Return (pubkey hex, fingerprint hex, "m/…" path) for a PSBT output."""
    derivations = psbt.outputs[i].bip32_derivations
    if not derivations:
        return None
    if len(derivations) != 1:
        raise ValueError(
            f"output {i} has {len(derivations)} derivations, expected one"
        )
    public_key, deriv = next(iter(derivations.items()))
    parts = [
        f"{index & ~HARDENED}'" if index & HARDENED else str(index)
        for index in deriv.derivation
    ]
    return public_key.sec().hex(), deriv.fingerprint.hex(), "m/" + "/".join(parts)


def input_sighashes(psbt: PSBT) -> list[bytes]:
    """BIP143 SIGHASH_ALL digest for each P2WPKH input."""
    sighashes = []
    for i, scope in enumerate(psbt.inputs):
        witness_utxo = scope.witness_utxo
        if witness_utxo is None:
            raise ValueError(f"input {i} has no witness_utxo")
        if witness_utxo.script_pubkey.script_type() != "p2wpkh":
            raise ValueError(f"input {i} is not P2WPKH")
        script_code = script.Script(
            b"\x76\xa9\x14" + witness_utxo.script_pubkey.data[2:] + b"\x88\xac"
        )
        sighashes.append(
            psbt.tx.sighash_segwit(i, script_code, witness_utxo.value, SIGHASH_ALL)
        )
    return sighashes


def sign_psbt(psbt: PSBT, wifs: Iterable[str]) -> PSBT:
    """Return a new PSBT with a partial signature on every input."""
    signed = PSBT.parse(psbt.serialize())
    wifs = list(wifs)
    key_by_script = {}
    for wif in wifs:
        key = private_key_from_wif(wif)
        key_by_script[script.p2wpkh(key.get_public_key()).serialize()] = (wif, key)
    sighashes = input_sighashes(signed)
    used = set()
    for i, scope in enumerate(signed.inputs):
        witness_utxo = scope.witness_utxo
        entry = (
            key_by_script.get(witness_utxo.script_pubkey.serialize())
            if witness_utxo is not None
            else None
        )
        if entry is None:
            raise ValueError(f"no private key matches input {i}")
        wif, key = entry
        used.add(wif)
        scope.partial_sigs[key.get_public_key()] = sign_digest(wif, sighashes[i]) + bytes(
            [SIGHASH_ALL]
        )
    unused = [wif for wif in wifs if wif not in used]
    if unused:
        raise ValueError(f"{len(unused)} WIF(s) match no input")
    return signed


def finalize_psbt(psbt: PSBT) -> str:
    """Attach [signature, pubkey] witnesses and return the raw transaction hex."""
    tx = Transaction.parse(psbt.tx.serialize())
    for i, scope in enumerate(psbt.inputs):
        if len(scope.partial_sigs) != 1:
            raise ValueError(
                f"input {i} must have exactly one partial signature, "
                f"has {len(scope.partial_sigs)}"
            )
        public_key, signature = next(iter(scope.partial_sigs.items()))
        tx.vin[i].witness = Witness(items=[signature, public_key.sec()])
    return tx.serialize().hex()


def extract_signatures(signed_tx_hex: str, unsigned_psbt: PSBT) -> list[InputSignature]:
    """Recover per-input signatures from a signed transaction."""
    tx = Transaction.parse(bytes.fromhex(signed_tx_hex))
    if tx.txid() != unsigned_psbt.tx.txid():
        raise ValueError("signed transaction does not match the unsigned PSBT")
    sighashes = input_sighashes(unsigned_psbt)
    results = []
    for i, scope in enumerate(unsigned_psbt.inputs):
        items = tx.vin[i].witness.items
        if len(items) != 2:
            raise ValueError(f"input {i} witness must have exactly two items")
        raw_sig, public_key_sec = items
        if len(raw_sig) < 9:
            raise ValueError(f"input {i} witness signature is too short")
        if len(public_key_sec) != 33 or public_key_sec[0] not in (0x02, 0x03):
            raise ValueError(f"input {i} witness has no compressed public key")
        public_key = ec.PublicKey.parse(public_key_sec)
        if (
            script.p2wpkh(public_key).serialize()
            != scope.witness_utxo.script_pubkey.serialize()
        ):
            raise ValueError(f"input {i} witness public key does not match its UTXO")
        results.append(
            InputSignature(
                index=i,
                public_key=public_key_sec.hex(),
                signature=raw_sig[:-1],
                sighash_type=raw_sig[-1],
                sighash=sighashes[i],
            )
        )
    return results
