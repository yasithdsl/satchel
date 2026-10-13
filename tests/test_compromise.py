"""E2E: a compromised agent can only lose its envelope; main funds need the Ledger."""

import json
import os
import secrets
import urllib.request
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from satchel_agent.agent import ShoppingAgent
from satchel_agent.clients import LaptopClient
from satchel_agent.compromise import LossSink
from satchel_agent.server import create_app as create_agent_app
from satchel_agent.tools import ToolBox
from satchel_laptop.app import create_app as create_laptop_app
from satchel_laptop.approver_client import ApproverClient
from satchel_laptop.main_funds import fund_main_funds
from satchel_laptop.signer_client import SignerClient
from satchel_laptop.state import LaptopState
from satchel_laptop.vault_client import VaultClient
from satchel_signer.app import create_app as create_signer_app
from satchel_vault.app import create_app as create_vault_app
from satchel_vault.vault import Vault

DICE = "1" * 50
PASSPHRASE = "compromise e2e passphrase"


def build_compromise_stack(approver, node, tmp_path):
    with urllib.request.urlopen(f"{approver}/address", timeout=30) as r:
        ledger = json.loads(r.read())["address"].lower()
    vault = Vault(tmp_path / "vault")
    vault.setup(DICE, PASSPHRASE, ledger)
    vault.unlock(PASSPHRASE)
    vault_client = VaultClient(http=TestClient(create_vault_app(vault)))
    state = LaptopState(tmp_path / "laptop" / "state.json")
    fund_main_funds(vault_client, node, state)

    laptop_app = create_laptop_app(
        vault_client,
        node,
        state,
        approver=ApproverClient(base_url=approver),
        signer=SignerClient(http=TestClient(create_signer_app())),
        flows_dir=tmp_path / "laptop",
        demo_mine=True,
    )
    laptop = LaptopClient(http=TestClient(laptop_app))
    marketplace = SimpleNamespace(rate=lambda: {"usd_per_btc": 100_000})

    def toolbox_factory(session_id, agent_id):
        return ToolBox(
            marketplace,
            laptop,
            node,
            agent_id,
            session_id=session_id,
            demo_auto="approve",
        )

    agent = ShoppingAgent(None, toolbox_factory)
    sessions = {}
    sink = LossSink(node, name=f"loss-sink-{secrets.token_hex(4)}")
    sink.ensure()
    client = TestClient(
        create_agent_app(
            agent, sessions, demo_controls=True, sink=sink, laptop=laptop
        )
    )
    session = agent.new_session()
    sessions[session.session_id] = session
    result = session.toolbox.run("request_budget", {"amount_usd": 200})
    assert result["granted"] is True
    assert result["budget_sats"] == 200_000
    return client, session, sink, state


def main_funds_snapshot(node, state):
    addresses = [e["address"] for e in state.main_fund_entries()]
    utxos = node.list_unspent(addresses)
    total = sum(u.amount_sats for u in utxos)
    return total, {(u.txid, u.vout) for u in utxos}


def spend_flows(tmp_path):
    flows = []
    for path in (tmp_path / "laptop" / "flows").glob("*.json"):
        flow = json.loads(path.read_text())
        if flow.get("kind") == "spend":
            flows.append(flow)
    return flows


def compromise_event_types():
    path = Path(os.environ["SATCHEL_EVENT_LOG"])
    return [
        json.loads(line)["type"]
        for line in path.read_text().splitlines()
        if json.loads(line)["type"].startswith("compromise_")
    ]


def event_records():
    path = Path(os.environ["SATCHEL_EVENT_LOG"])
    return [json.loads(line) for line in path.read_text().splitlines()]


def vault_used_nonces(tmp_path):
    inventory = json.loads((tmp_path / "vault" / "inventory.json").read_text())
    return list(inventory["used_nonces"])


def spend_hop(flow, name):
    return next(h for h in flow["hops"] if h["name"] == name)


@pytest.mark.speculos
@pytest.mark.regtest
def test_compromise_loss_bounded_by_envelope(approver, node, tmp_path):
    client, session, sink, state = build_compromise_stack(
        approver, node, tmp_path
    )
    main_before, outpoints = main_funds_snapshot(node, state)
    nonces_before = vault_used_nonces(tmp_path)
    events_before = len(event_records())

    response = client.post(
        "/demo/compromise",
        json={
            "session_id": session.session_id,
            "request_sats": 5_000_000,
            "demo_auto": "reject",
        },
    )
    assert response.status_code == 200
    report = response.json()
    node.mine_blocks(1, node.faucet_address())

    drained = report["drained_sats"]
    before = report["envelope_balance_before"]
    fee = before - drained
    assert before == 200_000, "a fresh satchel, funded from main funds"
    assert drained > 0
    assert 0 < fee < 2_000
    assert sink.balance()["confirmed_sats"] == drained

    spend = report["large_spend"]
    assert spend["broadcast"] is False
    assert spend["stage"] == "approval"

    main_after, after_outpoints = main_funds_snapshot(node, state)
    assert main_after == main_before
    assert after_outpoints == outpoints
    for txid, vout in outpoints:
        assert node.is_unspent(txid, vout, include_mempool=True)

    flows = spend_flows(tmp_path)
    assert len(flows) == 1
    names = [h["name"] for h in flows[0]["hops"]]
    assert names[-1] == "approval_rejected"
    assert "keys_released" not in names
    assert flows[0]["status"] == "failed"

    rejected_nonce = spend_hop(flows[0], "approval_rejected")["detail"]["nonce"]
    assert len(rejected_nonce) == 16
    nonces_after = vault_used_nonces(tmp_path)
    assert rejected_nonce not in nonces_after
    assert nonces_after == nonces_before
    vault_events = [
        e for e in event_records()[events_before:] if e["component"] == "vault"
    ]
    assert not [
        e
        for e in vault_events
        if e["type"]
        in ("release_requested", "spend_keys_released", "envelope_released")
    ]
    assert rejected_nonce not in json.dumps(vault_events)

    sink_view = client.get("/demo/loss-sink").json()
    assert sink_view["confirmed_sats"] == drained
    assert sink_view["last_address"] == report["sink_address"]

    assert compromise_event_types() == [
        "compromise_started",
        "compromise_envelope_drained",
        "compromise_large_spend_requested",
        "compromise_large_spend_blocked",
        "compromise_finished",
    ]


@pytest.mark.speculos
@pytest.mark.regtest
def test_compromise_follow_up_needs_ledger_approval(
    approver, node, tmp_path
):
    client, session, sink, state = build_compromise_stack(
        approver, node, tmp_path
    )
    main_before, _outpoints = main_funds_snapshot(node, state)

    response = client.post(
        "/demo/compromise",
        json={
            "session_id": session.session_id,
            "request_sats": 5_000_000,
            "demo_auto": "approve",
        },
    )
    assert response.status_code == 200
    report = response.json()
    spend = report["large_spend"]
    assert spend["broadcast"] is True
    assert spend["txid"]
    node.mine_blocks(1, node.faucet_address())

    flows = spend_flows(tmp_path)
    assert len(flows) == 1
    detail = next(
        h["detail"]
        for h in flows[0]["hops"]
        if h["name"] == "utxos_selected"
    )
    fee = detail["fee_sats"]
    main_after, _ = main_funds_snapshot(node, state)
    assert main_before - main_after == 5_000_000 + fee

    approval = json.loads(
        spend_hop(flows[0], "approval_received")["payload"]["payload"]
    )
    approved_nonce = approval["b"]["nonce"]
    assert approved_nonce in vault_used_nonces(tmp_path)
    released = [
        e
        for e in event_records()
        if e["component"] == "vault" and e["type"] == "spend_keys_released"
    ]
    assert [e["payload"]["nonce"] for e in released] == [approved_nonce]

    drained = report["drained_sats"]
    assert sink.balance()["confirmed_sats"] == drained + 5_000_000
    types = compromise_event_types()
    assert "compromise_large_spend_approved" in types
    assert types[-1] == "compromise_finished"
