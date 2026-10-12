"""End-to-end: a real Ledger (Speculos) gates every vault key release."""

import base64
import hashlib
import json
import os
import secrets
import shutil
import socket
import subprocess
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

REPO = Path(__file__).resolve().parents[1]
SPECULOS_URL = os.environ.get("SPECULOS_URL", "http://127.0.0.1:5001")
DICE = "1" * 25
PASSPHRASE = "ceremony passphrase"
BUDGET = 200_000

pytestmark = pytest.mark.speculos


def _speculos_up() -> bool:
    try:
        with urllib.request.urlopen(
            f"{SPECULOS_URL}/events?currentscreenonly=true", timeout=3
        ) as response:
            return response.status == 200
    except Exception:
        return False


def _http(url: str, body: dict | None = None, timeout: int = 180) -> tuple[int, dict]:
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


@pytest.fixture(scope="module")
def approver(tmp_path_factory):
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    if not _speculos_up():
        pytest.skip(f"Speculos not reachable at {SPECULOS_URL}")
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    workdir = tmp_path_factory.mktemp("approver")
    log = open(workdir / "approver.log", "w")
    env = {
        **os.environ,
        "APPROVER_PORT": str(port),
        "SATCHEL_APPROVER_DEMO_AUTOMATION": "1",
        "SPECULOS_URL": SPECULOS_URL,
        "SATCHEL_EVENT_LOG": str(workdir / "events.jsonl"),
    }
    proc = subprocess.Popen(
        ["node", "approver/src/main.ts"],
        cwd=REPO,
        env=env,
        stdout=log,
        stderr=log,
    )
    base = f"http://127.0.0.1:{port}"
    try:
        for _ in range(120):
            if proc.poll() is not None:
                raise RuntimeError(
                    f"approver exited early: {(workdir / 'approver.log').read_text()}"
                )
            try:
                status, health = _http(f"{base}/health", timeout=2)
                if status == 200:
                    break
            except Exception:
                pass
            time.sleep(0.5)
        else:
            raise RuntimeError("approver never became healthy")
        yield base
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
        log.close()


def _future_expiry() -> int:
    return (int(time.time()) + 90_000) // 60 * 60


def make_vault(tmp_path, ledger_address: str) -> Vault:
    vault = Vault(tmp_path / "vault")
    vault.setup(DICE, PASSPHRASE, ledger_address)
    vault.unlock(PASSPHRASE)
    return vault


def test_ledger_gated_envelope_release(approver, tmp_path):
    status, body = _http(f"{approver}/address")
    assert status == 200
    ledger = body["address"].lower()
    vault = make_vault(tmp_path, ledger)
    vault.allocate_envelopes(1, BUDGET)
    client = TestClient(create_vault_app(vault))

    plan = {
        "kind": "envelope_grant",
        "envelope_index": 0,
        "agent_id": "shopping-agent",
        "budget_sats": BUDGET,
        "expires_at": _future_expiry(),
    }
    status, approval_http = _http(
        f"{approver}/approve", {"plan": plan, "demo_auto": "approve"}
    )
    assert status == 200, approval_http
    approval = from_http(approval_http)
    assert approval.type == MessageType.LEDGER_APPROVAL
    assert approval.body["address"].lower() == ledger

    response = client.post("/release/envelope", json={"approval": approval_http})
    assert response.status_code == 200, response.text
    release = from_http(response.json())
    wallet = EnvelopeWallet.from_key_release(release, None)
    assert wallet.address == release.body["address"]

    replay = client.post("/release/envelope", json={"approval": approval_http})
    assert replay.status_code == 403

    status, rejected = _http(
        f"{approver}/approve",
        {
            "plan": {
                **plan,
                "envelope_index": 0,
                "agent_id": "other-agent",
            },
            "demo_auto": "reject",
        },
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
