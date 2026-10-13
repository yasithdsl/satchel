"""Satchel flow (fund from main funds, then hand over the key) against stubs."""

import base64
import hashlib
import json

import pytest
from embit import script
from embit.psbt import PSBT

from satchel_core.payloads import MessageType, Payload
from satchel_core.regtest import RPCError
from satchel_laptop.approver_client import ApprovalOutcome, ApproverError
from satchel_laptop.satchel import create_satchel
from satchel_laptop.vault_client import VaultRefused

from .test_spend import (
    MASTER,
    HonestSigner,
    OneApprover,
    StubNode,
    StubVault,
    approval,
    change_entry,
    funded_state,
)

NOW = 1_900_000_000
BUDGET = 200_000
SATCHEL = MASTER.envelope(0)


def reservation(index=0, budget=BUDGET, path=None):
    key = MASTER.envelope(index)
    return Payload(
        MessageType.ADDRESS_EXPORT,
        {
            "kind": "envelope",
            "fingerprint": MASTER.fingerprint,
            "addresses": [
                {
                    "index": index,
                    "path": path or key.path,
                    "address": key.address,
                    "public_key": key.public_key,
                    "budget_sats": budget,
                    "assigned_to": None,
                }
            ],
        },
    )


def key_release(agent_id="shopper-1", budget=BUDGET, index=0):
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
            "expires_at": NOW + 3660,
        },
    )


class SatchelVault(StubVault):
    def __init__(self, reserve=None, refuse_funding=None, refuse_key=None,
                 release=None, fail_verify=False):
        super().__init__(change_entry(), fail_verify=fail_verify)
        self.reserved = reserve or reservation()
        self.refuse_funding = refuse_funding
        self.refuse_key = refuse_key
        self.release = release or key_release()
        self.funding_calls = []
        self.proofs = []

    def reserve_satchel(self, budget_sats):
        return self.reserved

    def release_satchel_funding(self, approval_payload, psbt_payload):
        self.funding_calls.append(psbt_payload)
        if self.refuse_funding is not None:
            raise self.refuse_funding
        return self.release_spend(approval_payload, psbt_payload)

    def release_satchel(self, proof):
        self.proofs.append(proof)
        if self.refuse_key is not None:
            raise self.refuse_key
        return self.release


class ChainNode(StubNode):
    """Confirms a broadcast once a block is mined (or straight away)."""

    def __init__(self, utxos=(), confirm_on_broadcast=False):
        super().__init__(utxos)
        self.mined = 0
        self.confirm_on_broadcast = confirm_on_broadcast

    def faucet_address(self):
        return MASTER.receive(99).address

    def mine_blocks(self, count, address):
        self.mined += count
        return ["00" * 32] * count

    def call(self, method, *params):
        assert method == "gettxoutproof"
        if self.mined or self.confirm_on_broadcast:
            return "proof-for-" + params[0][0]
        raise RPCError(-5, "Transaction not yet in block")


def setup(tmp_path, amounts=(300_000,), **vault_kwargs):
    state, base = funded_state(tmp_path, amounts)
    node = ChainNode(base.utxos.values())
    return state, node, SatchelVault(**vault_kwargs)


def run(vault, node, state, tmp_path, approver=None, signer=None, **kwargs):
    kwargs.setdefault("demo_mine", True)
    return create_satchel(
        "shopper-1",
        BUDGET,
        vault=vault,
        approver=approver or OneApprover(),
        signer=signer or HonestSigner(),
        node=node,
        state=state,
        flows_dir=tmp_path,
        now=NOW,
        **kwargs,
    )


def flow_doc(tmp_path, result):
    return json.loads((tmp_path / "flows" / f"{result.flow_id}.json").read_text())


def test_one_approval_funds_the_satchel_then_hands_over_the_key(tmp_path):
    state, node, vault = setup(tmp_path)
    approver = OneApprover()
    signer = HonestSigner()
    result = run(vault, node, state, tmp_path, approver=approver, signer=signer)

    assert result.granted, result.reason
    assert result.envelope_index == 0
    assert result.budget_sats == BUDGET
    assert result.key_release.body["wif"] == SATCHEL.wif

    plan = approver.calls[0]
    psbt_payload = vault.funding_calls[0]
    raw = base64.b64decode(psbt_payload.body["psbt"])
    assert plan == {
        "kind": "satchel_grant",
        "satchel_index": 0,
        "agent_id": "shopper-1",
        "budget_sats": BUDGET,
        "expires_at": (NOW + 3600 + 59) // 60 * 60,
        "psbt_sha256": hashlib.sha256(raw).hexdigest(),
    }
    outputs = PSBT.parse(raw).tx.vout
    satchel_script = script.address_to_scriptpubkey(SATCHEL.address)
    assert [o.value for o in outputs if o.script_pubkey == satchel_script] == [BUDGET]

    assert len(node.broadcast_calls) == 1
    assert node.mined == 1
    proof = vault.proofs[0]
    assert proof.type == MessageType.FUNDING_PROOF
    txid = proof.body["txid"]
    assert proof.body == {"satchel_index": 0, "txid": txid, "proof": "proof-for-" + txid}
    assert state.funding_for(SATCHEL.address)[0]["txid"] == txid
    assert state.funding_for(SATCHEL.address)[0]["amount_sats"] == BUDGET

    doc = flow_doc(tmp_path, result)
    assert [h["name"] for h in doc["hops"]] == [
        "satchel_reserved",
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
        "funding_confirmed",
        "funding_proof_sent",
        "key_release_received",
        "key_delivered_to_agent",
    ]
    assert doc["status"] == "completed"
    assert SATCHEL.wif not in json.dumps(doc)
    key_hops = [h for h in doc["hops"] if h["payload"] and h["payload"]["type"] == "key_release"]
    assert len(key_hops) == 4
    assert all(h["redacted"] for h in key_hops)


def test_rejection_on_the_ledger_moves_no_money(tmp_path):
    state, node, vault = setup(tmp_path)
    outcome = ApprovalOutcome(False, None, "Rejected on the Ledger", "ab" * 8, "t")
    signer = HonestSigner()
    result = run(vault, node, state, tmp_path, approver=OneApprover(outcome), signer=signer)
    assert not result.granted
    assert result.stage == "approval"
    assert result.reason == "rejected on the Ledger"
    assert vault.funding_calls == []
    assert signer.calls == []
    assert node.broadcast_calls == []


def test_vault_refusal_stops_before_signing(tmp_path):
    state, node, vault = setup(tmp_path, refuse_funding=VaultRefused(403, "bad plan"))
    signer = HonestSigner()
    result = run(vault, node, state, tmp_path, signer=signer)
    assert not result.granted
    assert (result.stage, result.reason) == ("release", "bad plan")
    assert signer.calls == []


def test_dishonest_signature_is_never_broadcast_and_no_key(tmp_path):
    state, node, vault = setup(tmp_path, fail_verify=True)
    result = run(vault, node, state, tmp_path)
    assert not result.granted
    assert result.stage == "verification"
    assert "deterministic" in result.reason
    assert node.broadcast_calls == []
    assert vault.proofs == []


def test_unconfirmed_funding_does_not_release_the_key(tmp_path):
    state, node, vault = setup(tmp_path)
    result = run(
        vault, node, state, tmp_path, demo_mine=False,
        confirm_timeout=0.05, poll_interval=0.01,
    )
    assert not result.granted
    assert result.stage == "confirm"
    assert len(node.broadcast_calls) == 1
    assert vault.proofs == []


def test_waits_for_a_block_without_demo_mining(tmp_path):
    state, base, vault = setup(tmp_path)
    node = ChainNode(base.utxos.values(), confirm_on_broadcast=True)
    result = run(vault, node, state, tmp_path, demo_mine=False)
    assert result.granted
    assert node.mined == 0


def test_vault_key_refusal_surfaces(tmp_path):
    state, node, vault = setup(tmp_path, refuse_key=VaultRefused(403, "funding is not confirmed"))
    result = run(vault, node, state, tmp_path)
    assert not result.granted
    assert (result.stage, result.reason) == ("key", "funding is not confirmed")


@pytest.mark.parametrize(
    "release",
    [
        key_release(agent_id="someone-else"),
        key_release(budget=BUDGET + 1),
        key_release(index=1),
    ],
)
def test_mismatched_key_release_is_not_delivered(tmp_path, release):
    state, node, vault = setup(tmp_path, release=release)
    result = run(vault, node, state, tmp_path)
    assert not result.granted
    assert result.stage == "deliver"
    doc = flow_doc(tmp_path, result)
    assert "key_delivered_to_agent" not in [h["name"] for h in doc["hops"]]


def test_insufficient_main_funds_skip_the_ledger(tmp_path):
    state, node, vault = setup(tmp_path, amounts=(50_000,))
    approver = OneApprover()
    result = run(vault, node, state, tmp_path, approver=approver)
    assert not result.granted
    assert result.stage == "select"
    assert approver.calls == []


@pytest.mark.parametrize(
    "reserve",
    [
        reservation(budget=BUDGET + 1),
        reservation(path="m/84'/1'/0'/1'/0'"),
    ],
)
def test_reservation_must_match_the_request(tmp_path, reserve):
    state, node, vault = setup(tmp_path, reserve=reserve)
    with pytest.raises(ValueError):
        run(vault, node, state, tmp_path)


def test_approver_error_fails_the_flow(tmp_path):
    state, node, vault = setup(tmp_path)

    class Down:
        def approve(self, plan, demo_auto=None):
            raise ApproverError("approver down")

    with pytest.raises(ApproverError):
        run(vault, node, state, tmp_path, approver=Down())
    docs = [json.loads(p.read_text()) for p in (tmp_path / "flows").glob("*.json")]
    assert docs[0]["status"] == "failed"
    assert docs[0]["result"]["stage"] == "approval"


@pytest.mark.parametrize("agent_id,budget", [("bad\nid", BUDGET), ("ok", 0), ("ok", True)])
def test_bad_agent_and_budget_rejected(tmp_path, agent_id, budget):
    state, node, vault = setup(tmp_path)
    with pytest.raises(ValueError):
        create_satchel(
            agent_id, budget, vault=vault, approver=OneApprover(),
            signer=HonestSigner(), node=node, state=state, flows_dir=tmp_path,
        )
