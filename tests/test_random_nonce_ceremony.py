"""Random-nonce demo: the network accepts it, the vault refuses (regtest)."""

import secrets

import pytest
from fastapi.testclient import TestClient

from satchel_core.keys import MasterKey
from satchel_core.payloads import (
    MessageType,
    Payload,
    from_http,
    to_http,
)
from satchel_core.transactions import Output, SpendInput, build_psbt
from satchel_signer.app import create_app as create_signer_app
from satchel_vault.app import create_app as create_vault_app
from satchel_vault.seed import read_seed_file
from satchel_vault.vault import Vault

DICE = "1" * 25
PASSPHRASE = "ceremony passphrase"
LEDGER = "0xdad77910dbdfde764fc21fcd4e74d71bbaca6d8d"


@pytest.fixture
def signer_client():
    def make(random_nonce: bool = False):
        return TestClient(create_signer_app(random_nonce=random_nonce))

    return make


@pytest.fixture
def funded_vault(node, tmp_path):
    vault = Vault(tmp_path / "vault")
    vault.setup(DICE, PASSPHRASE, LEDGER)
    vault.unlock(PASSPHRASE)
    master = MasterKey.from_seed(
        read_seed_file(tmp_path / "vault" / "seed.json", PASSPHRASE)
    )
    keys = [master.receive(0), master.receive(1)]
    node.fund_address(keys[0].address, 60_000)
    node.fund_address(keys[1].address, 40_000)
    by_address = {key.address: key for key in keys}
    utxos = node.list_unspent([key.address for key in keys])
    dest = MasterKey.from_seed(secrets.token_bytes(32)).receive(0).address
    psbt = build_psbt(
        [
            SpendInput(
                u.txid,
                u.vout,
                u.amount_sats,
                by_address[u.address].public_key,
                path=by_address[u.address].path,
            )
            for u in utxos
        ],
        [Output(dest, 80_000)],
        Output(keys[0].address, 19_000),
        fingerprint=vault.fingerprint,
    )
    unsigned = Payload(
        MessageType.UNSIGNED_PSBT, {"psbt": psbt.to_base64()}
    )
    return {
        "client": TestClient(create_vault_app(vault)),
        "unsigned": unsigned,
        "keys": keys,
    }


def _release(keys):
    return Payload(
        MessageType.KEY_RELEASE,
        {
            "kind": "signing",
            "keys": [{"path": k.path, "wif": k.wif} for k in keys],
        },
    )


def _sign(signer, unsigned, keys):
    response = signer.post(
        "/sign",
        json={"psbt": to_http(unsigned), "keys": to_http(_release(keys))},
    )
    assert response.status_code == 200
    return from_http(response.json())


def _verify(vault_client, unsigned, signed):
    response = vault_client.post(
        "/verify",
        json={"psbt": to_http(unsigned), "signed": to_http(signed)},
    )
    assert response.status_code == 200
    return from_http(response.json()).body


@pytest.mark.regtest
def test_random_nonce_accepted_by_network_refused_by_vault(
    node, funded_vault, signer_client
):
    vault = funded_vault
    signer = signer_client()
    response = signer.post("/demo/random-nonce", json={"enabled": True})
    assert response.json() == {"enabled": True}
    signed = _sign(signer, vault["unsigned"], vault["keys"])
    accepted = node.call("testmempoolaccept", [signed.body["tx"]])[0]
    assert accepted["allowed"], accepted
    result = _verify(vault["client"], vault["unsigned"], signed)
    assert result["result"] == "fail"
    assert all(f["scope"] == "input" for f in result["failures"])
    assert all("deterministic" in f["reason"] for f in result["failures"])
    assert {f["index"] for f in result["failures"]} == set(
        range(len(vault["keys"]))
    )


@pytest.mark.regtest
def test_flag_off_signs_normally_vault_passes(node, funded_vault, signer_client):
    vault = funded_vault
    signer = signer_client()
    signed = _sign(signer, vault["unsigned"], vault["keys"])
    accepted = node.call("testmempoolaccept", [signed.body["tx"]])[0]
    assert accepted["allowed"], accepted
    assert (
        _verify(vault["client"], vault["unsigned"], signed)["result"] == "pass"
    )
