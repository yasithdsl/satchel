"""End-to-end: a real Ledger (Speculos) gates every vault key release."""

import base64
import hashlib
import json
import secrets
import time
import urllib.request
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from satchel_agent.wallet import EnvelopeWallet
from satchel_core.keys import MasterKey
from satchel_core.payloads import MessageType, Payload, from_http, to_http
from satchel_core.transactions import Output, SpendInput, build_psbt
from satchel_signer.app import create_app as create_signer_app
from satchel_vault.app import create_app as create_vault_app
from satchel_vault.seed import read_seed_file
from satchel_vault.vault import Vault

DICE = "1" * 50
PASSPHRASE = "ceremony passphrase"
BUDGET = 200_000

pytestmark = pytest.mark.speculos


def _http(url: str, body: dict | None = None, timeout: int = 180):
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(
        url,
        data=data,
        headers={"content-type": "application/json"} if data else {},
        method="POST" if data else "GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def _future_expiry() -> int:
    return (int(time.time()) + 90_000) // 60 * 60


def make_vault(tmp_path, ledger_address: str) -> Vault:
    vault = Vault(tmp_path / "vault")
    vault.setup(DICE, PASSPHRASE, ledger_address)
    vault.unlock(PASSPHRASE)
    return vault


def satchel_funding(vault: Vault, master: MasterKey, address: str):
    """Main funds (vault receive keys) paying exactly BUDGET to the satchel."""
    inputs = [
        SpendInput(
            secrets.token_hex(32),
            0,
            150_000,
            master.receive(i).public_key,
            path=master.receive(i).path,
        )
        for i in range(2)
    ]
    change = master.change(0)
    psbt = build_psbt(
        inputs,
        [Output(address, BUDGET)],
        Output(
            change.address,
            300_000 - BUDGET - 1_000,
            path=change.path,
            public_key=change.public_key,
        ),
        fingerprint=vault.fingerprint,
    )
    return psbt.serialize()


def test_ledger_gated_satchel_funding(approver, tmp_path):
    status, body = _http(f"{approver}/address")
    assert status == 200
    ledger = body["address"].lower()
    vault = make_vault(tmp_path, ledger)
    master = MasterKey.from_seed(
        read_seed_file(tmp_path / "vault" / "seed.json", PASSPHRASE)
    )
    client = TestClient(create_vault_app(vault))
    satchel = from_http(
        client.post("/satchels/reserve", json={"budget_sats": BUDGET}).json()
    ).body["addresses"][0]
    raw = satchel_funding(vault, master, satchel["address"])
    psbt_http = to_http(
        Payload(MessageType.UNSIGNED_PSBT, {"psbt": base64.b64encode(raw).decode()})
    )
    plan = {
        "kind": "satchel_grant",
        "satchel_index": satchel["index"],
        "agent_id": "shopping-agent",
        "budget_sats": BUDGET,
        "expires_at": _future_expiry(),
        "psbt_sha256": hashlib.sha256(raw).hexdigest(),
    }
    status, approval_http = _http(
        f"{approver}/approve", {"plan": plan, "demo_auto": "approve"}
    )
    assert status == 200, approval_http
    approval = from_http(approval_http)
    assert approval.type == MessageType.LEDGER_APPROVAL
    assert approval.body["address"].lower() == ledger
    assert approval.body["text"].startswith("Create a 0.002 BTC satchel #0 ")

    response = client.post(
        "/release/satchel-funding",
        json={"approval": approval_http, "psbt": psbt_http},
    )
    assert response.status_code == 200, response.text
    keys = from_http(response.json())
    assert sorted(k["path"] for k in keys.body["keys"]) == sorted(
        master.receive(i).path for i in range(2)
    )
    assert master.envelope(0).wif not in response.text

    replay = client.post(
        "/release/satchel-funding",
        json={"approval": approval_http, "psbt": psbt_http},
    )
    assert replay.status_code == 403

    status, rejected = _http(
        f"{approver}/approve",
        {"plan": {**plan, "agent_id": "other-agent"}, "demo_auto": "reject"},
    )
    assert status == 409
    assert rejected["status"] == "rejected"
    inventory = json.loads(
        (tmp_path / "vault" / "inventory.json").read_text()
    )
    assert rejected["nonce"] not in inventory["used_nonces"]


@pytest.mark.regtest
def test_ledger_gated_spend_release(approver, node, tmp_path):
    status, body = _http(f"{approver}/address")
    assert status == 200
    vault = make_vault(tmp_path, body["address"].lower())
    client = TestClient(create_vault_app(vault))
    signer = TestClient(create_signer_app())
    master = MasterKey.from_seed(
        read_seed_file(tmp_path / "vault" / "seed.json", PASSPHRASE)
    )
    exported = vault.export_receive_addresses(2)
    entries = exported.body["addresses"]
    for entry, sats in zip(entries, (60_000, 40_000)):
        node.fund_address(entry["address"], sats)
    utxos = node.list_unspent([e["address"] for e in entries])
    by_address = {e["address"]: e for e in entries}
    inputs = [
        SpendInput(
            u.txid,
            u.vout,
            u.amount_sats,
            by_address[u.address]["public_key"],
            path=by_address[u.address]["path"],
        )
        for u in utxos
    ]
    dest = MasterKey.from_seed(secrets.token_bytes(32)).receive(0).address
    change = master.change(0)
    amount = 80_000
    psbt = build_psbt(
        inputs,
        [Output(dest, amount)],
        Output(
            change.address,
            sum(u.amount_sats for u in utxos) - amount - 1_000,
            path=change.path,
            public_key=change.public_key,
        ),
        fingerprint=vault.fingerprint,
    )
    raw = psbt.serialize()
    unsigned = Payload(
        MessageType.UNSIGNED_PSBT,
        {"psbt": base64.b64encode(raw).decode()},
    )
    plan = {
        "kind": "large_spend",
        "amount_sats": amount,
        "destination": dest,
        "purpose": "laptop",
        "psbt_sha256": hashlib.sha256(raw).hexdigest(),
    }
    status, approval_http = _http(
        f"{approver}/approve", {"plan": plan, "demo_auto": "approve"}
    )
    assert status == 200, approval_http

    response = client.post(
        "/release/spend",
        json={"approval": approval_http, "psbt": to_http(unsigned)},
    )
    assert response.status_code == 200, response.text
    release = from_http(response.json())
    assert release.body["kind"] == "signing"
    assert len(release.body["keys"]) == len(utxos)

    signed_response = signer.post(
        "/sign",
        json={"psbt": to_http(unsigned), "keys": to_http(release)},
    )
    assert signed_response.status_code == 200, signed_response.text
    signed = from_http(signed_response.json())
    verify = client.post(
        "/verify",
        json={"psbt": to_http(unsigned), "signed": to_http(signed)},
    )
    assert verify.status_code == 200
    assert from_http(verify.json()).body["result"] == "pass"
    accepted = node.call("testmempoolaccept", [signed.body["tx"]])[0]
    assert accepted["allowed"], accepted
