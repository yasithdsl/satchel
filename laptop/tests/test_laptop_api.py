"""Laptop HTTP API tests with stub client and node."""

import httpx
from fastapi.testclient import TestClient

from satchel_core.keys import MasterKey
from satchel_core.payloads import MessageType, Payload, from_http
from satchel_core.regtest import NodeUnavailable
from satchel_laptop.app import create_app
from satchel_laptop.approver_client import ApprovalOutcome, ApproverError
from satchel_laptop.state import LaptopState

from .test_envelopes import StubNode, export_payload, utxo
from .test_grant import envelope_export, funded_node
from .test_grant import StubVault as GrantStubVault
from .test_spend import HonestSigner, change_entry, funded_state
from .test_spend import StubVault as SpendStubVault

SEED = bytes.fromhex("000102030405060708090a0b0c0d0e0f")
MASTER = MasterKey.from_seed(SEED)


class StubVaultClient:
    def __init__(self, payload=None, error=None):
        self._payload = payload
        self._error = error

    def fetch_envelopes(self):
        if self._error is not None:
            raise self._error
        return self._payload


def test_get_envelopes(tmp_path):
    payload = export_payload(count=2)
    address = payload.body["addresses"][0]["address"]
    node = StubNode(utxos=[utxo(address)])
    app = create_app(StubVaultClient(payload), node, LaptopState(tmp_path / "s.json"))
    body = TestClient(app).get("/envelopes").json()
    statuses = {e["index"]: e for e in body["envelopes"]}
    assert statuses[0]["status"] == "unassigned"
    assert statuses[0]["balance_sats"] == 50_000
    assert statuses[1]["status"] == "unfunded"
    assert statuses[1]["budget_sats"] == 50_000


def test_vault_unreachable_returns_502(tmp_path):
    client = StubVaultClient(error=httpx.ConnectError("connection refused"))
    app = create_app(client, StubNode(), LaptopState(tmp_path / "s.json"))
    response = TestClient(app).get("/envelopes")
    assert response.status_code == 502
    assert "vault" in response.json()["detail"]


def test_bad_vault_payload_returns_502(tmp_path):
    client = StubVaultClient(error=ValueError("bad vault payload"))
    app = create_app(client, StubNode(), LaptopState(tmp_path / "s.json"))
    response = TestClient(app).get("/envelopes")
    assert response.status_code == 502


def test_node_unreachable_returns_503(tmp_path):
    class DownNode:
        def list_unspent(self, addresses):
            raise NodeUnavailable("connection refused")

    client = StubVaultClient(export_payload(count=1))
    app = create_app(client, DownNode(), LaptopState(tmp_path / "s.json"))
    response = TestClient(app).get("/envelopes")
    assert response.status_code == 503
    assert "bitcoind" in response.json()["detail"]


class GrantedApprover:
    def __init__(self, outcome):
        self.outcome = outcome

    def approve(self, plan, demo_auto=None):
        return self.outcome


class FailApprover:
    def approve(self, plan, demo_auto=None):
        raise ApproverError("approver down")


def test_grants_endpoint(tmp_path):
    export = envelope_export([100_000])
    key = MASTER.envelope(0)
    release = Payload(
        MessageType.KEY_RELEASE,
        {
            "kind": "envelope",
            "envelope_index": 0,
            "path": key.path,
            "address": key.address,
            "public_key": key.public_key,
            "wif": key.wif,
            "budget_sats": 100_000,
            "agent_id": "shopper-1",
            "expires_at": 1_900_000_000,
        },
    )
    vault = GrantStubVault(export, release)
    app = create_app(
        vault,
        funded_node(export),
        LaptopState(tmp_path / "s.json"),
        approver=GrantedApprover(
            ApprovalOutcome(True, Payload(MessageType.LEDGER_APPROVAL, {
                "plan": {}, "text": "t", "nonce": "ab" * 8,
                "signature": "0x" + "11" * 65, "address": "0x" + "22" * 20,
                "path": "44'/60'/0'/0/0"}), None, None, None)
        ),
    )
    client = TestClient(app)
    response = client.post(
        "/grants", json={"agent_id": "shopper-1", "budget_sats": 50_000}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["granted"] is True
    assert body["envelope_index"] == 0
    assert from_http(body["key_release"]).body["wif"] == key.wif


def test_grants_rejection_and_validation(tmp_path):
    export = envelope_export([100_000])
    vault = GrantStubVault(export, None)
    app = create_app(
        vault,
        funded_node(export),
        LaptopState(tmp_path / "s.json"),
        approver=GrantedApprover(
            ApprovalOutcome(False, None, "Rejected on the Ledger", "ab" * 8, "t")
        ),
    )
    client = TestClient(app)
    response = client.post(
        "/grants", json={"agent_id": "shopper-1", "budget_sats": 50_000}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["granted"] is False
    assert body["reason"] == "rejected on the Ledger"
    assert vault.release_calls == []
    assert client.post(
        "/grants", json={"agent_id": "bad\nid", "budget_sats": 5}
    ).status_code == 422


def test_grants_approver_error_503(tmp_path):
    export = envelope_export([100_000])
    app = create_app(
        GrantStubVault(export, None),
        funded_node(export),
        LaptopState(tmp_path / "s.json"),
        approver=FailApprover(),
    )
    response = TestClient(app).post(
        "/grants", json={"agent_id": "ok", "budget_sats": 50_000}
    )
    assert response.status_code == 503


def test_spends_endpoint(tmp_path):
    state, node = funded_state(tmp_path, (50_000,))
    vault = SpendStubVault(change_entry())
    signer = HonestSigner()
    app = create_app(
        vault,
        node,
        state,
        approver=GrantedApprover(
            ApprovalOutcome(
                True, Payload(MessageType.LEDGER_APPROVAL, {}), None, None, None
            )
        ),
        signer=signer,
    )
    dest = MASTER.envelope(9).address
    response = TestClient(app).post(
        "/spends",
        json={"destination": dest, "amount_sats": 10_000, "purpose": "test"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["broadcast"] is True
    assert body["stage"] == "broadcast" and body["txid"]
    assert signer.calls
    bad = TestClient(app).post(
        "/spends",
        json={"destination": "bc1qmain", "amount_sats": 10_000, "purpose": "x"},
    )
    assert bad.status_code == 422
