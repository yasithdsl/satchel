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
from .test_satchel import setup as satchel_setup
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


def test_health(tmp_path):
    app = create_app(
        StubVaultClient(None), StubNode(), LaptopState(tmp_path / "s.json")
    )
    assert TestClient(app).get("/health").json() == {"ok": True}


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


def test_grants_endpoint_creates_a_satchel(tmp_path):
    state, node, vault = satchel_setup(tmp_path)
    app = create_app(
        vault,
        node,
        state,
        approver=GrantedApprover(
            ApprovalOutcome(True, Payload(MessageType.LEDGER_APPROVAL, {}), None, None, None)
        ),
        signer=HonestSigner(),
        demo_mine=True,
    )
    response = TestClient(app).post(
        "/grants", json={"agent_id": "shopper-1", "budget_sats": 200_000}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["granted"] is True
    assert body["envelope_index"] == 0
    assert body["budget_sats"] == 200_000
    assert from_http(body["key_release"]).body["wif"] == MASTER.envelope(0).wif
    assert node.mined == 1


def test_grants_rejection_and_validation(tmp_path):
    state, node, vault = satchel_setup(tmp_path)
    app = create_app(
        vault,
        node,
        state,
        approver=GrantedApprover(
            ApprovalOutcome(False, None, "Rejected on the Ledger", "ab" * 8, "t")
        ),
        signer=HonestSigner(),
    )
    client = TestClient(app)
    response = client.post(
        "/grants", json={"agent_id": "shopper-1", "budget_sats": 200_000}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["granted"] is False
    assert body["stage"] == "approval"
    assert body["reason"] == "rejected on the Ledger"
    assert vault.funding_calls == []
    assert client.post(
        "/grants", json={"agent_id": "bad\nid", "budget_sats": 5}
    ).status_code == 422


def test_grants_need_approver_and_signer(tmp_path):
    state, node, vault = satchel_setup(tmp_path)
    no_signer = create_app(vault, node, state, approver=FailApprover())
    response = TestClient(no_signer).post(
        "/grants", json={"agent_id": "ok", "budget_sats": 200_000}
    )
    assert response.status_code == 503
    down = create_app(vault, node, state, approver=FailApprover(), signer=HonestSigner())
    response = TestClient(down).post(
        "/grants", json={"agent_id": "ok", "budget_sats": 200_000}
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


def test_main_funds_empty(tmp_path):
    app = create_app(
        StubVaultClient(), StubNode(), LaptopState(tmp_path / "s.json")
    )
    assert TestClient(app).get("/main-funds").json() == {
        "fingerprint": None,
        "addresses": 0,
        "utxos": 0,
        "balance_sats": 0,
        "available_sats": 0,
    }


def test_main_funds_summary_and_mempool_spent(tmp_path):
    state, _ = funded_state(tmp_path, (50_000, 30_000))
    entries = state.main_fund_entries()

    class FundsNode:
        def __init__(self, utxos, mempool_spent):
            self.utxos = list(utxos)
            self.mempool_spent = set(mempool_spent)

        def list_unspent(self, addresses):
            wanted = set(addresses)
            return [u for u in self.utxos if u.address in wanted]

        def is_unspent(self, txid, vout, include_mempool=True):
            return (txid, vout) not in self.mempool_spent

    kept = utxo(entries[0]["address"], amount=50_000, txid="aa" * 32)
    spent = utxo(entries[1]["address"], amount=30_000, txid="bb" * 32)
    node = FundsNode([kept, spent], {(spent.txid, spent.vout)})
    app = create_app(StubVaultClient(), node, state)
    body = TestClient(app).get("/main-funds").json()
    assert body == {
        "fingerprint": MASTER.fingerprint,
        "addresses": 2,
        "utxos": 2,
        "balance_sats": 80_000,
        "available_sats": 50_000,
    }
