"""End-to-end coordinator flows: Ledger approval -> vault release -> spend."""

import json
import secrets
import urllib.request
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from satchel_agent.wallet import EnvelopeWallet
from satchel_core.keys import MasterKey
from satchel_laptop.approver_client import ApproverClient
from satchel_laptop.funding import fund_envelopes
from satchel_laptop.grant import grant_envelope
from satchel_laptop.main_funds import fund_main_funds
from satchel_laptop.signer_client import SignerClient
from satchel_laptop.spend import large_spend
from satchel_laptop.state import LaptopState
from satchel_laptop.vault_client import VaultClient
from satchel_signer.app import create_app as create_signer_app
from satchel_vault.app import create_app as create_vault_app
from satchel_vault.vault import Vault

DICE = "1" * 25
PASSPHRASE = "ceremony passphrase"

pytestmark = [pytest.mark.speculos, pytest.mark.regtest]


def _get_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=30) as response:
        return json.loads(response.read())


def make_coordinator(approver: str, node, tmp_path) -> dict:
    ledger = _get_json(f"{approver}/address")["address"].lower()
    vault = Vault(tmp_path / "vault")
    vault.setup(DICE, PASSPHRASE, ledger)
    vault.unlock(PASSPHRASE)
    return {
        "vault": VaultClient(http=TestClient(create_vault_app(vault))),
        "approver": ApproverClient(base_url=approver),
        "state": LaptopState(tmp_path / "laptop" / "state.json"),
        "vault_obj": vault,
    }


def flow_doc(tmp_path, flow_id: str) -> dict:
    return json.loads(
        (tmp_path / "laptop" / "flows" / f"{flow_id}.json").read_text()
    )


def test_grant_envelope_end_to_end(approver, node, tmp_path):
    ctx = make_coordinator(approver, node, tmp_path)
    ctx["vault_obj"].allocate_envelopes(2, 100_000)
    export2 = ctx["vault_obj"].allocate_envelopes(1, 200_000)
    assert [e["budget_sats"] for e in export2.body["addresses"]] == [200_000]
    funded = fund_envelopes(ctx["vault"], node, ctx["state"])
    assert len(funded) == 3

    result = grant_envelope(
        "shopping-agent",
        150_000,
        vault=ctx["vault"],
        approver=ctx["approver"],
        node=node,
        state=ctx["state"],
        demo_auto="approve",
        flows_dir=tmp_path / "laptop",
    )
    assert result.granted, result.reason
    assert result.envelope_index == 2
    assert result.budget_sats == 200_000
    assert isinstance(result.wallet, EnvelopeWallet)

    dest = MasterKey.from_seed(secrets.token_bytes(32)).receive(0).address
    txid = result.wallet.pay(dest, 50_000)
    node.mine_blocks(1, node.faucet_address())
    tx = node.get_transaction(txid)
    assert any(
        v["scriptPubKey"].get("address") == dest
        and round(v["value"] * 100_000_000) == 50_000
        for v in tx["vout"]
    )

    rejected = grant_envelope(
        "other-agent",
        50_000,
        vault=ctx["vault"],
        approver=ctx["approver"],
        node=node,
        state=ctx["state"],
        demo_auto="reject",
        flows_dir=tmp_path / "laptop",
    )
    assert not rejected.granted
    assert rejected.wallet is None
    assert rejected.reason == "rejected on the Ledger"
    export = ctx["vault"].fetch_envelopes()
    entry = [
        e for e in export.body["addresses"] if e["budget_sats"] == 100_000
    ]
    assert all(e["assigned_to"] is None for e in entry)
    flow = flow_doc(tmp_path, rejected.flow_id)
    assert "key_release_received" not in [h["name"] for h in flow["hops"]]
    grant_flow = flow_doc(tmp_path, result.flow_id)
    assert [h["name"] for h in grant_flow["hops"]] == [
        "envelopes_fetched",
        "plan_sent_to_approver",
        "approval_received",
        "approval_sent_to_vault",
        "key_release_received",
        "key_delivered_to_agent",
    ]


def test_large_spend_end_to_end(approver, node, tmp_path):
    ctx = make_coordinator(approver, node, tmp_path)
    funded = fund_main_funds(
        ctx["vault"], node, ctx["state"], flows_dir=tmp_path / "laptop"
    )
    assert [f["amount_sats"] for f in funded] == [
        50_000_000,
        30_000_000,
        20_000_000,
    ]
    signer_http = TestClient(create_signer_app())
    signer = SignerClient(http=signer_http)

    dest = MasterKey.from_seed(secrets.token_bytes(32)).receive(0).address
    result = large_spend(
        dest,
        60_000_000,
        "laptop",
        vault=ctx["vault"],
        approver=ctx["approver"],
        signer=signer,
        node=node,
        state=ctx["state"],
        demo_auto="approve",
        flows_dir=tmp_path / "laptop",
    )
    assert result.broadcast, result.reason
    assert result.stage == "broadcast" and result.txid
    node.mine_blocks(1, node.faucet_address())
    tx = node.get_transaction(result.txid)
    change_addr = [
        e["address"]
        for e in ctx["state"].main_fund_entries()
        if e["kind"] == "change"
    ]
    assert len(change_addr) == 1
    paid = {
        v["scriptPubKey"].get("address"): round(v["value"] * 100_000_000)
        for v in tx["vout"]
    }
    assert paid[dest] == 60_000_000
    assert change_addr[0] in paid
    flow = flow_doc(tmp_path, result.flow_id)
    assert [h["name"] for h in flow["hops"]] == [
        "change_address_exported",
        "utxos_selected",
        "psbt_built",
        "plan_sent_to_approver",
        "approval_received",
        "approval_sent_to_vault",
        "keys_released",
        "keys_sent_to_signer",
        "signed_tx_received",
        "verification_received",
        "broadcast",
    ]

    signer_http.post("/demo/random-nonce", json={"enabled": True})
    mempool_before = node.call("getrawmempool")
    dest2 = MasterKey.from_seed(secrets.token_bytes(32)).receive(0).address
    rogue = large_spend(
        dest2,
        30_000_000,
        "again",
        vault=ctx["vault"],
        approver=ctx["approver"],
        signer=signer,
        node=node,
        state=ctx["state"],
        demo_auto="approve",
        flows_dir=tmp_path / "laptop",
    )
    assert not rogue.broadcast
    assert rogue.stage == "verification"
    assert "deterministic" in rogue.reason
    assert node.call("getrawmempool") == mempool_before
    rogue_flow = flow_doc(tmp_path, rogue.flow_id)
    hop = next(h for h in rogue_flow["hops"] if h["name"] == "utxos_selected")
    for outpoint in hop["detail"]["outpoints"]:
        assert node.is_unspent(outpoint["txid"], outpoint["vout"])
