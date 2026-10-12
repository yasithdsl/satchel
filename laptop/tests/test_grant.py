"""Envelope grant flow against stub vault/approver clients."""

import json
import secrets
from pathlib import Path

import pytest

from satchel_core.keys import MasterKey
from satchel_core.payloads import MessageType, Payload
from satchel_core.regtest import Utxo
from satchel_laptop.approver_client import ApprovalOutcome, ApproverError
from satchel_laptop.grant import grant_envelope
from satchel_laptop.state import LaptopState
from satchel_laptop.vault_client import VaultRefused

SEED = bytes.fromhex("000102030405060708090a0b0c0d0e0f")
MASTER = MasterKey.from_seed(SEED)
NOW = 1_900_000_000


def envelope_export(budgets: list[int]) -> Payload:
    addresses = []
    for i, budget in enumerate(budgets):
        key = MASTER.envelope(i)
        addresses.append(
            {
                "index": i,
                "path": key.path,
                "address": key.address,
                "public_key": key.public_key,
                "budget_sats": budget,
                "assigned_to": None,
            }
        )
    return Payload(
        MessageType.ADDRESS_EXPORT,
        {
            "kind": "envelope",
            "fingerprint": MASTER.fingerprint,
            "addresses": addresses,
        },
    )


class StubNode:
    def __init__(self, utxos=()):
        self.utxos = list(utxos)

    def list_unspent(self, addresses):
        wanted = set(addresses)
        return [u for u in self.utxos if u.address in wanted]


class StubVault:
    def __init__(self, export: Payload, release: Payload | None = None, refuse=None):
        self.export = export
        self.release = release
        self.refuse = refuse
        self.release_calls = []

    def fetch_envelopes(self):
        return self.export

    def release_envelope(self, approval):
        self.release_calls.append(approval)
        if self.refuse is not None:
            raise self.refuse
        return self.release


class StubApprover:
    def __init__(self, outcome: ApprovalOutcome):
        self.outcome = outcome
        self.calls = []

    def approve(self, plan, demo_auto=None):
        self.calls.append((plan, demo_auto))
        return self.outcome


def release_payload(index: int, agent_id: str, budget: int) -> Payload:
    key = MASTER.envelope(index)
    return Payload(
        MessageType.KEY_RELEASE,
        {
            "kind": "envelope",
            "envelope_index": index,
            "path": key.path,
            "address": key.address,
            "public_key": key.public_key,
            "wif": key.wif,
            "budget_sats": budget,
            "agent_id": agent_id,
            "expires_at": NOW + 3600,
        },
    )


def approval_payload(plan: dict) -> Payload:
    return Payload(
        MessageType.LEDGER_APPROVAL,
        {
            "plan": plan,
            "text": "text",
            "nonce": "a" * 16,
            "signature": "0x" + "11" * 65,
            "address": "0x" + "22" * 20,
            "path": "44'/60'/0'/0/0",
        },
    )


def funded_node(payload: Payload) -> StubNode:
    return StubNode(
        [
            Utxo(
                txid=secrets.token_hex(32),
                vout=0,
                address=e["address"],
                amount_sats=e["budget_sats"],
                script_pubkey="0014" + "ab" * 20,
                height=100,
                coinbase=False,
            )
            for e in payload.body["addresses"]
        ]
    )


def test_picks_smallest_fitting_envelope(tmp_path):
    export = envelope_export([200_000, 100_000, 50_000])
    release = release_payload(1, "shopping-agent", 100_000)
    vault = StubVault(export, release)
    approver = StubApprover(ApprovalOutcome(True, approval_payload({}), None, None, None))
    node = funded_node(export)
    state = LaptopState(tmp_path / "state.json")
    result = grant_envelope(
        "shopping-agent",
        60_000,
        vault=vault,
        approver=approver,
        node=node,
        state=state,
        flows_dir=tmp_path / "flows",
        now=NOW,
    )
    assert result.granted
    assert result.envelope_index == 1
    assert result.budget_sats == 100_000
    assert result.key_release is release
    assert result.key_release.type == MessageType.KEY_RELEASE
    assert result.key_release.body["kind"] == "envelope"
    assert result.key_release.body["envelope_index"] == 1
    assert result.key_release.body["agent_id"] == "shopping-agent"
    plan, demo_auto = approver.calls[0]
    assert plan["envelope_index"] == 1
    assert plan["budget_sats"] == 100_000
    assert plan["expires_at"] % 60 == 0
    assert plan["expires_at"] >= NOW + 3600


def test_picks_lowest_index_on_budget_tie(tmp_path):
    export = envelope_export([100_000, 100_000])
    release = release_payload(0, "a", 100_000)
    vault = StubVault(export, release)
    approver = StubApprover(ApprovalOutcome(True, approval_payload({}), None, None, None))
    result = grant_envelope(
        "a",
        50_000,
        vault=vault,
        approver=approver,
        node=funded_node(export),
        state=LaptopState(tmp_path / "state.json"),
        flows_dir=tmp_path / "flows",
        now=NOW,
    )
    assert result.envelope_index == 0


def test_no_fitting_envelope_skips_approver(tmp_path):
    export = envelope_export([50_000])
    approver = StubApprover(ApprovalOutcome(True, approval_payload({}), None, None, None))
    result = grant_envelope(
        "a",
        100_000,
        vault=StubVault(export),
        approver=approver,
        node=funded_node(export),
        state=LaptopState(tmp_path / "state.json"),
        flows_dir=tmp_path / "flows",
        now=NOW,
    )
    assert not result.granted
    assert result.key_release is None
    assert "no unassigned funded envelope" in result.reason
    assert approver.calls == []


def test_rejection_skips_vault(tmp_path):
    export = envelope_export([100_000])
    vault = StubVault(export)
    approver = StubApprover(
        ApprovalOutcome(False, None, "Rejected on the Ledger", "ab" * 8, "text")
    )
    result = grant_envelope(
        "a",
        50_000,
        vault=vault,
        approver=approver,
        node=funded_node(export),
        state=LaptopState(tmp_path / "state.json"),
        flows_dir=tmp_path / "flows",
        now=NOW,
    )
    assert not result.granted
    assert result.reason == "rejected on the Ledger"
    assert vault.release_calls == []
    flow = json.loads(
        (tmp_path / "flows" / "flows" / f"{result.flow_id}.json").read_text()
    )
    names = [h["name"] for h in flow["hops"]]
    assert names == [
        "envelopes_fetched",
        "plan_sent_to_approver",
        "approval_rejected",
    ]
    assert flow["status"] == "failed"


def test_vault_refusal_surfaces_reason(tmp_path):
    export = envelope_export([100_000])
    release = release_payload(0, "a", 100_000)
    vault = StubVault(export, release, refuse=VaultRefused(409, "envelope is already assigned"))
    approver = StubApprover(ApprovalOutcome(True, approval_payload({}), None, None, None))
    result = grant_envelope(
        "a",
        50_000,
        vault=vault,
        approver=approver,
        node=funded_node(export),
        state=LaptopState(tmp_path / "state.json"),
        flows_dir=tmp_path / "flows",
        now=NOW,
    )
    assert not result.granted
    assert result.reason == "envelope is already assigned"


def test_mismatched_key_release_not_delivered(tmp_path):
    export = envelope_export([100_000])
    release = release_payload(0, "other-agent", 100_000)
    vault = StubVault(export, release)
    approver = StubApprover(ApprovalOutcome(True, approval_payload({}), None, None, None))
    result = grant_envelope(
        "a",
        50_000,
        vault=vault,
        approver=approver,
        node=funded_node(export),
        state=LaptopState(tmp_path / "state.json"),
        flows_dir=tmp_path / "flows",
        now=NOW,
    )
    assert not result.granted
    assert result.key_release is None
    assert "key_release" in result.reason
    flow = json.loads(
        (tmp_path / "flows" / "flows" / f"{result.flow_id}.json").read_text()
    )
    names = [h["name"] for h in flow["hops"]]
    assert names[-1] == "key_release_received"
    assert "key_delivered_to_agent" not in names


def test_hop_order_and_redaction(tmp_path):
    export = envelope_export([100_000])
    release = release_payload(0, "a", 100_000)
    vault = StubVault(export, release)
    approver = StubApprover(ApprovalOutcome(True, approval_payload({}), None, None, None))
    result = grant_envelope(
        "a",
        50_000,
        vault=vault,
        approver=approver,
        node=funded_node(export),
        state=LaptopState(tmp_path / "state.json"),
        flows_dir=tmp_path / "flows",
        now=NOW,
    )
    flow_path = tmp_path / "flows" / "flows" / f"{result.flow_id}.json"
    flow = json.loads(flow_path.read_text())
    names = [h["name"] for h in flow["hops"]]
    assert names == [
        "envelopes_fetched",
        "plan_sent_to_approver",
        "approval_received",
        "approval_sent_to_vault",
        "key_release_received",
        "key_delivered_to_agent",
    ]
    assert flow["status"] == "completed"
    wif = MASTER.envelope(0).wif
    assert wif not in flow_path.read_text()
    key_hops = [
        h for h in flow["hops"] if h["payload"] and h["payload"]["type"] == "key_release"
    ]
    assert key_hops and all(h["redacted"] for h in key_hops)
    import os

    events = Path(os.environ["SATCHEL_EVENT_LOG"]).read_text()
    assert wif not in events


def test_approver_error_fails_flow(tmp_path):
    class DownApprover:
        def approve(self, plan, demo_auto=None):
            raise ApproverError("approver unreachable")

    export = envelope_export([100_000])
    with pytest.raises(ApproverError):
        grant_envelope(
            "a",
            50_000,
            vault=StubVault(export),
            approver=DownApprover(),
            node=funded_node(export),
            state=LaptopState(tmp_path / "state.json"),
            flows_dir=tmp_path / "flows",
            now=NOW,
        )
    flows = sorted((tmp_path / "flows" / "flows").glob("*.json"))
    assert len(flows) == 1
    doc = json.loads(flows[0].read_text())
    assert doc["status"] == "failed"
    assert doc["result"]["stage"] == "approval"
    import os

    events = Path(os.environ["SATCHEL_EVENT_LOG"]).read_text()
    assert '"grant_failed"' in events


def test_bad_agent_and_budget_rejected(tmp_path):
    with pytest.raises(ValueError):
        grant_envelope(
            "bad\nagent",
            50_000,
            vault=StubVault(envelope_export([])),
            approver=StubApprover(None),
            node=StubNode(),
            state=LaptopState(tmp_path / "s.json"),
            flows_dir=tmp_path / "f",
            now=NOW,
        )
    for bad in (0, -1, True, 1.5):
        with pytest.raises(ValueError):
            grant_envelope(
                "ok",
                bad,
                vault=StubVault(envelope_export([])),
                approver=StubApprover(None),
                node=StubNode(),
                state=LaptopState(tmp_path / "s.json"),
                flows_dir=tmp_path / "f",
                now=NOW,
            )


def test_demo_sizes_pick_exact_fit(tmp_path):
    export = envelope_export([100_000, 200_000, 500_000])
    release = release_payload(1, "a", 200_000)
    vault = StubVault(export, release)
    approver = StubApprover(ApprovalOutcome(True, approval_payload({}), None, None, None))
    result = grant_envelope(
        "a",
        200_000,
        vault=vault,
        approver=approver,
        node=funded_node(export),
        state=LaptopState(tmp_path / "state.json"),
        flows_dir=tmp_path / "flows",
        now=NOW,
    )
    assert result.granted
    assert result.envelope_index == 1
    plan, _demo = approver.calls[0]
    assert plan["budget_sats"] == 200_000
