"""Full ceremony: vault PSBT -> signer signs -> vault verifies (regtest)."""

import os
import secrets

import pytest
from embit.transaction import Transaction
from embit.util.secp256k1 import ecdsa_sign, ecdsa_signature_serialize_der
from fastapi.testclient import TestClient

from satchel_core.keys import MasterKey
from satchel_core.payloads import (
    MessageType,
    Payload,
    from_http,
    to_http,
)
from satchel_core.signing import private_key_from_wif, verify_digest
from satchel_core.transactions import (
    Output,
    SpendInput,
    build_psbt,
    input_sighashes,
)
from satchel_signer.app import create_app as create_signer_app
from satchel_vault.app import create_app as create_vault_app
from satchel_vault.seed import read_seed_file
from satchel_vault.vault import Vault

DICE = "1" * 25
PASSPHRASE = "ceremony passphrase"
LEDGER = "0xdad77910dbdfde764fc21fcd4e74d71bbaca6d8d"


def make_vault(tmp_path):
    vault = Vault(tmp_path / "vault")
    vault.setup(DICE, PASSPHRASE, LEDGER)
    vault.unlock(PASSPHRASE)
    return vault


@pytest.mark.regtest
def test_signing_ceremony(node, tmp_path):
    vault = make_vault(tmp_path)
    master = MasterKey.from_seed(
        read_seed_file(tmp_path / "vault" / "seed.json", PASSPHRASE)
    )
    k0, k1 = master.receive(0), master.receive(1)
    node.fund_address(k0.address, 60_000)
    node.fund_address(k1.address, 40_000)
    by_address = {k0.address: k0, k1.address: k1}
    utxos = node.list_unspent([k0.address, k1.address])
    inputs = [
        SpendInput(
            u.txid,
            u.vout,
            u.amount_sats,
            by_address[u.address].public_key,
            path=by_address[u.address].path,
        )
        for u in utxos
    ]
    dest = MasterKey.from_seed(secrets.token_bytes(32)).receive(0).address
    psbt = build_psbt(
        inputs,
        [Output(dest, 80_000)],
        Output(k0.address, 19_000),
        fingerprint=vault.fingerprint,
    )
    unsigned = Payload(MessageType.UNSIGNED_PSBT, {"psbt": psbt.to_base64()})
    release = Payload(
        MessageType.KEY_RELEASE,
        {
            "kind": "signing",
            "keys": [
                {"path": k.path, "wif": k.wif} for k in (k0, k1)
            ],
        },
    )

    signer_client = TestClient(create_signer_app())
    vault_client = TestClient(create_vault_app(vault))

    def verify(signed: Payload):
        response = vault_client.post(
            "/verify",
            json={"psbt": to_http(unsigned), "signed": to_http(signed)},
        )
        assert response.status_code == 200
        return from_http(response.json()).body

    response = signer_client.post(
        "/sign",
        json={"psbt": to_http(unsigned), "keys": to_http(release)},
    )
    assert response.status_code == 200
    signed = from_http(response.json())
    accepted = node.call("testmempoolaccept", [signed.body["tx"]])[0]
    assert accepted["allowed"], accepted
    assert verify(signed)["result"] == "pass"

    tampered = Transaction.parse(bytes.fromhex(signed.body["tx"]))
    tampered.vout[0].value += 1
    changed = Payload(
        MessageType.SIGNED_TX,
        {"tx": tampered.serialize().hex(), "txid": signed.body["txid"]},
    )
    changed_result = verify(changed)
    assert changed_result["result"] == "fail"
    assert any(f["scope"] == "output" for f in changed_result["failures"])

    key0 = by_address[utxos[0].address]
    sighash = input_sighashes(psbt)[0]
    forged = (
        ecdsa_signature_serialize_der(
            ecdsa_sign(
                sighash,
                private_key_from_wif(key0.wif).secret,
                None,
                os.urandom(32),
            )
        )
        + b"\x01"
    )
    assert verify_digest(key0.public_key, sighash, forged[:-1])
    nontx = Transaction.parse(bytes.fromhex(signed.body["tx"]))
    items = list(nontx.vin[0].witness.items)
    items[0] = forged
    nontx.vin[0].witness.items = items
    forged_payload = Payload(
        MessageType.SIGNED_TX,
        {"tx": nontx.serialize().hex(), "txid": signed.body["txid"]},
    )
    accepted = node.call("testmempoolaccept", [forged_payload.body["tx"]])[0]
    assert accepted["allowed"], accepted
    forged_result = verify(forged_payload)
    assert forged_result["result"] == "fail"
    assert any(
        "deterministic" in f["reason"] for f in forged_result["failures"]
    )
