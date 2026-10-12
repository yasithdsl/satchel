"""Pre-broadcast verification: recompute the honest signatures byte for byte.

This is the only vault module allowed to call sign_digest and read .wif — it
re-derives child keys to check the signer's work. It never outputs, logs or
emits a signature or key, only pass/fail and plain-English reasons.
"""

from __future__ import annotations

from embit import ec, script
from embit.psbt import PSBT
from embit.transaction import Transaction, TransactionOutput

from satchel_core.keys import NETWORK, MasterKey
from satchel_core.signing import sign_digest, verify_digest
from satchel_core.transactions import input_derivation, input_sighashes

SIGHASH_ALL_BYTE = 0x01


def _describe(output: TransactionOutput) -> str:
    try:
        destination = output.script_pubkey.address(NETWORK)
    except Exception:
        destination = f"script {output.script_pubkey.serialize().hex()}"
    return f"{output.value} sats to {destination}"


def _check_input_signature(
    master: MasterKey,
    fingerprint: str,
    approved: PSBT,
    sighash: bytes,
    tx: Transaction,
    i: int,
    fail,
) -> None:
    witness = tx.vin[i].witness
    items = list(witness.items) if witness is not None else []
    if len(items) != 2:
        return fail(i, f"input {i} witness must have exactly two items")
    raw_sig, pubkey_sec = items
    if (
        not isinstance(pubkey_sec, bytes)
        or len(pubkey_sec) != 33
        or pubkey_sec[0] not in (0x02, 0x03)
    ):
        return fail(i, f"input {i} has no compressed public key in its witness")
    try:
        public_key = ec.PublicKey.parse(pubkey_sec)
    except ValueError:
        return fail(i, f"input {i} witness public key does not parse")
    utxo = approved.inputs[i].witness_utxo
    if (
        utxo is None
        or script.p2wpkh(public_key).serialize()
        != utxo.script_pubkey.serialize()
    ):
        return fail(
            i, f"input {i} is signed by a key that does not match its UTXO"
        )
    if len(raw_sig) < 9:
        return fail(i, f"input {i} signature is too short")
    if raw_sig[-1] != SIGHASH_ALL_BYTE:
        return fail(
            i,
            f"input {i} signature uses sighash type 0x{raw_sig[-1]:02x}, "
            "expected SIGHASH_ALL",
        )
    deriv = input_derivation(approved, i)
    if deriv is None:
        return fail(
            i, f"input {i} has no key derivation in the approved transaction"
        )
    _, deriv_fingerprint, path = deriv
    if deriv_fingerprint.lower() != fingerprint.lower():
        return fail(i, f"input {i} is derived from a different master key")
    try:
        key = master.derive(path)
    except ValueError:
        return fail(i, f"input {i} derivation path is not a hardened path")
    if key.public_key != pubkey_sec.hex():
        return fail(
            i, f"input {i} is not signed by the key at the approved path"
        )
    der = raw_sig[:-1]
    if not verify_digest(pubkey_sec.hex(), sighash, der):
        return fail(
            i, f"input {i} signature is not valid for the approved transaction"
        )
    if der != sign_digest(key.wif, sighash):
        return fail(
            i,
            f"input {i} signature is valid but differs from the deterministic "
            "signature the vault expects; the signer did not use the shared "
            "RFC6979 nonce and may be leaking data",
        )


def verify_transaction(
    master: MasterKey, fingerprint: str, approved: PSBT, signed_tx_hex: str
) -> dict:
    """Compare a signed transaction against the approved PSBT, field by field,
    and check every signature equals the deterministic honest signature."""
    approved_tx = approved.tx
    failures = []

    def fail(scope, index, reason):
        failures.append({"scope": scope, "index": index, "reason": reason})

    try:
        tx = Transaction.parse(bytes.fromhex(signed_tx_hex))
    except Exception:
        fail("transaction", None, "signed transaction does not parse")
        return _result(approved_tx.txid().hex(), len(approved_tx.vin), failures)

    if tx.version != approved_tx.version:
        fail(
            "transaction",
            None,
            f"version {tx.version} but the approved transaction has "
            f"version {approved_tx.version}",
        )
    if tx.locktime != approved_tx.locktime:
        fail(
            "transaction",
            None,
            f"locktime {tx.locktime} but the approved transaction has "
            f"locktime {approved_tx.locktime}",
        )

    failed_inputs = set()

    def fail_input(i, reason):
        if i not in failed_inputs:
            failed_inputs.add(i)
            fail("input", i, reason)

    outpoints_match = len(tx.vin) == len(approved_tx.vin)
    if not outpoints_match:
        fail(
            "transaction",
            None,
            f"{len(tx.vin)} inputs but the approved transaction has "
            f"{len(approved_tx.vin)}",
        )
    else:
        for i, (vin, expected) in enumerate(zip(tx.vin, approved_tx.vin)):
            if vin.txid != expected.txid or vin.vout != expected.vout:
                outpoints_match = False
                fail_input(
                    i,
                    f"input {i} spends {vin.txid.hex()}:{vin.vout} but the "
                    f"approved transaction spends "
                    f"{expected.txid.hex()}:{expected.vout}",
                )
            elif vin.sequence != expected.sequence:
                fail_input(
                    i,
                    f"input {i} has sequence 0x{vin.sequence:08x} but the "
                    f"approved transaction has 0x{expected.sequence:08x}",
                )
            if vin.script_sig is not None and vin.script_sig.data != b"":
                fail_input(i, f"input {i} has a non-empty scriptSig")

    if len(tx.vout) != len(approved_tx.vout):
        fail(
            "transaction",
            None,
            f"{len(tx.vout)} outputs but the approved transaction has "
            f"{len(approved_tx.vout)}",
        )
    else:
        for i, (vout, expected) in enumerate(zip(tx.vout, approved_tx.vout)):
            if (
                vout.value != expected.value
                or vout.script_pubkey.serialize()
                != expected.script_pubkey.serialize()
            ):
                fail(
                    "output",
                    i,
                    f"output {i} pays {_describe(vout)} but the approved "
                    f"transaction pays {_describe(expected)}",
                )

    if not outpoints_match:
        fail(
            "transaction",
            None,
            "inputs could not be checked because they differ from the "
            "approved transaction",
        )
    else:
        sighashes = input_sighashes(approved)
        for i in range(len(approved_tx.vin)):
            if i in failed_inputs:
                continue
            _check_input_signature(
                master, fingerprint, approved, sighashes[i], tx, i, fail_input
            )

    if not failures and tx.txid() != approved_tx.txid():
        fail(
            "transaction",
            None,
            "transaction hash differs from the approved transaction",
        )
    return _result(approved_tx.txid().hex(), len(approved_tx.vin), failures)


def _result(txid_hex: str, n_inputs: int, failures: list[dict]) -> dict:
    return {
        "result": "fail" if failures else "pass",
        "txid": txid_hex,
        "inputs": n_inputs,
        "failures": failures,
    }
