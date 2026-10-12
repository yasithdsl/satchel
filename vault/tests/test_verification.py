"""Offline pre-broadcast verification: honest signers pass, forgeries fail."""

import json
import os
import secrets
from pathlib import Path

import pytest
from embit.transaction import Transaction
from embit.util.secp256k1 import (
    ecdsa_sign,
    ecdsa_signature_serialize_der,
)

from satchel_core.keys import MasterKey
from satchel_core.payloads import MessageType, Payload, encode
from satchel_core.signing import private_key_from_wif, sign_digest, verify_digest
from satchel_core.transactions import (
    Output,
    SpendInput,
    build_psbt,
    finalize_psbt,
    input_sighashes,
    sign_psbt,
)
from satchel_vault.seed import read_seed_file
from satchel_vault.vault import Vault, VaultLocked

from .test_vault import DICE, PASSPHRASE, make_vault


def event_log() -> str:
    return Path(os.environ["SATCHEL_EVENT_LOG"]).read_text()


def event_types() -> list[str]:
    return [json.loads(line)["type"] for line in event_log().splitlines()]


def setup_case(tmp_path, n=2, fingerprint=None, paths=True):
    vault = make_vault(tmp_path)
    master = MasterKey.from_seed(
        read_seed_file(tmp_path / "vault" / "seed.json", PASSPHRASE)
    )
    keys = [master.receive(i) for i in range(n)]
    dest = MasterKey.from_seed(secrets.token_bytes(32)).receive(0).address
    inputs = [
        SpendInput(
            secrets.token_hex(32),
            i,
            50_000,
            key.public_key,
            path=key.path if paths else None,
        )
        for i, key in enumerate(keys)
    ]
    psbt = build_psbt(
        inputs,
        [Output(dest, 80_000)],
        Output(keys[0].address, 19_000),
        fingerprint=fingerprint if fingerprint is not None else vault.fingerprint,
    )
    unsigned = Payload(
        MessageType.UNSIGNED_PSBT, {"psbt": psbt.to_base64()}
    )
    raw = finalize_psbt(sign_psbt(psbt, [k.wif for k in keys]))
    txid = Transaction.parse(bytes.fromhex(raw)).txid().hex()
    signed = Payload(MessageType.SIGNED_TX, {"tx": raw, "txid": txid})
    return vault, master, keys, psbt, unsigned, signed


def forged_nonce_sig(wif: str, sighash: bytes) -> bytes:
    secret = private_key_from_wif(wif).secret
    sig = ecdsa_sign(sighash, secret, None, os.urandom(32))
    return ecdsa_signature_serialize_der(sig) + b"\x01"


def test_honest_signature_passes(tmp_path):
    vault, master, keys, psbt, unsigned, signed = setup_case(tmp_path)
    result = vault.verify(unsigned, signed)
    assert result.type == MessageType.VERIFICATION_RESULT
    assert result.body["result"] == "pass"
    assert result.body["failures"] == []
    assert result.body["inputs"] == 2
    assert "verification_passed" in event_types()


def test_changed_output_fails(tmp_path):
    vault, master, keys, psbt, unsigned, signed = setup_case(tmp_path)
    tx = Transaction.parse(bytes.fromhex(signed.body["tx"]))
    tx.vout[0].value += 1
    tampered = Payload(
        MessageType.SIGNED_TX,
        {"tx": tx.serialize().hex(), "txid": signed.body["txid"]},
    )
    result = vault.verify(unsigned, tampered)
    assert result.body["result"] == "fail"
    assert any(f["scope"] == "output" for f in result.body["failures"])


def test_random_nonce_signature_fails(tmp_path):
    vault, master, keys, psbt, unsigned, signed = setup_case(tmp_path)
    sighashes = input_sighashes(psbt)
    forged = forged_nonce_sig(keys[0].wif, sighashes[0])
    assert verify_digest(keys[0].public_key, sighashes[0], forged[:-1])
    assert forged[:-1] != sign_digest(keys[0].wif, sighashes[0])

    tx = Transaction.parse(bytes.fromhex(signed.body["tx"]))
    items = list(tx.vin[0].witness.items)
    items[0] = forged
    tx.vin[0].witness.items = items
    tampered = Payload(
        MessageType.SIGNED_TX,
        {"tx": tx.serialize().hex(), "txid": signed.body["txid"]},
    )
    result = vault.verify(unsigned, tampered)
    assert result.body["result"] == "fail"
    assert len(result.body["failures"]) == 1
    failure = result.body["failures"][0]
    assert failure["index"] == 0
    assert "deterministic" in failure["reason"]


def test_missing_derivation_fails(tmp_path):
    vault = make_vault(tmp_path)
    master = MasterKey.from_seed(
        read_seed_file(tmp_path / "vault" / "seed.json", PASSPHRASE)
    )
    keys = [master.receive(0), master.receive(1)]
    dest = MasterKey.from_seed(secrets.token_bytes(32)).receive(0).address
    inputs = [
        SpendInput(secrets.token_hex(32), 0, 50_000, keys[0].public_key, path=keys[0].path),
        SpendInput(secrets.token_hex(32), 1, 50_000, keys[1].public_key),
    ]
    psbt = build_psbt(
        inputs,
        [Output(dest, 80_000)],
        Output(keys[0].address, 19_000),
        fingerprint=vault.fingerprint,
    )
    unsigned = Payload(MessageType.UNSIGNED_PSBT, {"psbt": psbt.to_base64()})
    raw = finalize_psbt(sign_psbt(psbt, [k.wif for k in keys]))
    signed = Payload(
        MessageType.SIGNED_TX,
        {"tx": raw, "txid": Transaction.parse(bytes.fromhex(raw)).txid().hex()},
    )
    result = vault.verify(unsigned, signed)
    assert result.body["result"] == "fail"
    assert any("derivation" in f["reason"] for f in result.body["failures"])


def test_foreign_fingerprint_fails(tmp_path):
    vault, master, keys, psbt, unsigned, signed = setup_case(
        tmp_path, fingerprint="00000000"
    )
    result = vault.verify(unsigned, signed)
    assert result.body["result"] == "fail"
    assert any(
        "different master key" in f["reason"] for f in result.body["failures"]
    )


def test_swapped_witnesses_fail(tmp_path):
    vault, master, keys, psbt, unsigned, signed = setup_case(tmp_path)
    tx = Transaction.parse(bytes.fromhex(signed.body["tx"]))
    tx.vin[0].witness, tx.vin[1].witness = tx.vin[1].witness, tx.vin[0].witness
    tampered = Payload(
        MessageType.SIGNED_TX,
        {"tx": tx.serialize().hex(), "txid": signed.body["txid"]},
    )
    result = vault.verify(unsigned, tampered)
    assert result.body["result"] == "fail"


def test_wrong_sighash_byte_fails(tmp_path):
    vault, master, keys, psbt, unsigned, signed = setup_case(tmp_path)
    tx = Transaction.parse(bytes.fromhex(signed.body["tx"]))
    items = list(tx.vin[0].witness.items)
    items[0] = items[0][:-1] + b"\x81"
    tx.vin[0].witness.items = items
    tampered = Payload(
        MessageType.SIGNED_TX,
        {"tx": tx.serialize().hex(), "txid": signed.body["txid"]},
    )
    result = vault.verify(unsigned, tampered)
    assert result.body["result"] == "fail"
    assert any("sighash" in f["reason"] for f in result.body["failures"])


def test_locked_vault_refuses(tmp_path):
    vault = Vault(tmp_path / "vault")
    vault.setup(DICE, PASSPHRASE)
    master = MasterKey.from_seed(
        read_seed_file(tmp_path / "vault" / "seed.json", PASSPHRASE)
    )
    keys = [master.receive(0)]
    inputs = [
        SpendInput(
            secrets.token_hex(32), 0, 50_000, keys[0].public_key, path=keys[0].path
        )
    ]
    psbt = build_psbt(
        inputs,
        [Output(master.envelope(0).address, 40_000)],
        fingerprint=vault.fingerprint,
    )
    unsigned = Payload(MessageType.UNSIGNED_PSBT, {"psbt": psbt.to_base64()})
    raw = finalize_psbt(sign_psbt(psbt, [keys[0].wif]))
    signed = Payload(MessageType.SIGNED_TX, {"tx": raw, "txid": "00" * 32})
    with pytest.raises(VaultLocked):
        vault.verify(unsigned, signed)


def test_bad_payload_types_rejected(tmp_path):
    vault, master, keys, psbt, unsigned, signed = setup_case(tmp_path)
    with pytest.raises(ValueError):
        vault.verify(signed, signed)
    with pytest.raises(ValueError):
        vault.verify(unsigned, unsigned)
    with pytest.raises(ValueError):
        vault.verify(Payload(MessageType.UNSIGNED_PSBT, {}), signed)
    with pytest.raises(ValueError):
        vault.verify(
            unsigned, Payload(MessageType.SIGNED_TX, {"tx": 12, "txid": "x"})
        )


def test_results_and_events_never_leak_signatures(tmp_path):
    vault, master, keys, psbt, unsigned, signed = setup_case(tmp_path)
    honest = Transaction.parse(bytes.fromhex(signed.body["tx"]))
    honest_sigs = [vin.witness.items[0].hex() for vin in honest.vin]
    wifs = [k.wif for k in keys]

    sighashes = input_sighashes(psbt)
    forged = forged_nonce_sig(keys[0].wif, sighashes[0])
    tx = honest
    items = list(tx.vin[0].witness.items)
    items[0] = forged
    tx.vin[0].witness.items = items
    tampered = Payload(
        MessageType.SIGNED_TX,
        {"tx": tx.serialize().hex(), "txid": signed.body["txid"]},
    )

    passing = vault.verify(unsigned, signed)
    failing = vault.verify(unsigned, tampered)
    assert failing.body["result"] == "fail"
    log = event_log()
    assert "verification_passed" in event_types()
    assert "verification_failed" in event_types()
    for secret in [*honest_sigs, forged.hex(), *wifs]:
        assert secret not in encode(passing)
        assert secret not in encode(failing)
        assert secret not in log
