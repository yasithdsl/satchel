"""Satchels: one Ledger approval funds a fresh satchel from main funds, and the
vault hands over its key only once that exact funding is verified and
confirmed."""

import base64
import hashlib
import json
import os
import secrets
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from satchel_agent.wallet import EnvelopeWallet
from satchel_core.keys import MasterKey
from satchel_core.payloads import MessageType, Payload, to_http
from satchel_core.transactions import (
    Output,
    SpendInput,
    build_psbt,
    finalize_psbt,
    sign_psbt,
)
from satchel_vault.app import create_app
from satchel_vault.approvals import ApprovalRejected, EnvelopeUnavailable
from satchel_vault.vault import Vault, VaultLocked

from .proofs import build_proof
from .test_approvals import approve_payload, satchel_plan
from .test_release import (
    LEDGER,
    NONCE,
    PASSPHRASE,
    event_types,
    make_vault,
    master_of,
    unsigned_psbt_payload,
)

BUDGET = 200_000
FUTURE = 4_102_444_800


def funding_psbt(
    vault: Vault,
    master: MasterKey,
    destination: str,
    amount: int = BUDGET,
    extra_outputs: list[Output] | None = None,
):
    """Main funds (two receive keys) paying `destination`, change to the vault."""
    inputs = [
        SpendInput(
            txid=secrets.token_hex(32),
            vout=0,
            amount_sats=150_000,
            public_key=master.receive(i).public_key,
            path=master.receive(i).path,
        )
        for i in range(2)
    ]
    change = master.change(0)
    psbt = build_psbt(
        inputs,
        [Output(destination, amount), *(extra_outputs or [])],
        Output(
            change.address,
            300_000 - amount - 1_000 - sum(o.amount_sats for o in extra_outputs or []),
            path=change.path,
            public_key=change.public_key,
        ),
        fingerprint=vault.fingerprint,
    )
    return psbt, psbt.serialize()


def reserve(vault: Vault, budget: int = BUDGET) -> dict:
    return vault.reserve_satchel(budget).body["addresses"][0]


def grant(vault, master, *, nonce=NONCE, budget=BUDGET, **plan_overrides):
    """Reserve a satchel and build its funding PSBT plus a signed approval."""
    satchel = reserve(vault, budget)
    psbt, raw = funding_psbt(vault, master, satchel["address"], budget)
    plan = satchel_plan(
        satchel_index=satchel["index"],
        budget_sats=budget,
        expires_at=FUTURE,
        psbt_sha256=hashlib.sha256(raw).hexdigest(),
    )
    plan.update(plan_overrides)
    return satchel, psbt, raw, approve_payload(plan, nonce)


def sign_and_verify(vault: Vault, psbt, keys: Payload, raw: bytes) -> str:
    """The honest signer signs; the vault verifies (and records the funding)."""
    tx_hex = finalize_psbt(sign_psbt(psbt, [k["wif"] for k in keys.body["keys"]]))
    result = vault.verify(
        unsigned_psbt_payload(raw), Payload(MessageType.SIGNED_TX, {"tx": tx_hex})
    )
    assert result.body["result"] == "pass", result.body
    return result.body["txid"]


def proof_for(index: int, txid: str, others: int = 3, proof: str | None = None):
    ids = [secrets.token_hex(32) for _ in range(others)] + [txid]
    return Payload(
        MessageType.FUNDING_PROOF,
        {
            "satchel_index": index,
            "txid": txid,
            "proof": proof or build_proof(ids, len(ids) - 1),
        },
    )


def inventory(tmp_path) -> dict:
    return json.loads((tmp_path / "vault" / "inventory.json").read_text())


def test_reserve_derives_fresh_hardened_keys_and_shares_only_public_data(tmp_path):
    vault = make_vault(tmp_path)
    master = master_of(tmp_path)
    first = vault.reserve_satchel(BUDGET)
    second = vault.reserve_satchel(100_000)
    assert first.type == MessageType.ADDRESS_EXPORT
    assert first.body["kind"] == "envelope"
    entries = first.body["addresses"] + second.body["addresses"]
    assert [e["index"] for e in entries] == [0, 1]
    for entry in entries:
        key = master.envelope(entry["index"])
        assert entry["path"] == f"m/84'/1'/0'/2'/{entry['index']}'"
        assert entry["address"] == key.address
        assert entry["public_key"] == key.public_key
        assert "wif" not in entry
    assert [e["budget_sats"] for e in entries] == [BUDGET, 100_000]
    assert [e["status"] for e in inventory(tmp_path)["envelopes"]] == [
        "reserved",
        "reserved",
    ]
    assert "satchel_reserved" in event_types()


@pytest.mark.parametrize("budget", [0, 999, True, "200000", 100_000_001])
def test_reserve_validates_budget(tmp_path, budget):
    vault = make_vault(tmp_path)
    with pytest.raises(ValueError):
        vault.reserve_satchel(budget)


def test_full_chain_funds_then_hands_over_the_key(tmp_path):
    vault = make_vault(tmp_path)
    master = master_of(tmp_path)
    satchel, psbt, raw, approval = grant(vault, master)

    keys = vault.release_satchel_funding(approval, unsigned_psbt_payload(raw))
    assert keys.body["kind"] == "signing"
    released_paths = sorted(k["path"] for k in keys.body["keys"])
    assert released_paths == sorted(master.receive(i).path for i in range(2))
    assert master.envelope(0).wif not in json.dumps(keys.body)
    doc = inventory(tmp_path)
    assert doc["used_nonces"] == [NONCE]
    assert doc["envelopes"][0]["status"] == "funding"
    assert doc["envelopes"][0]["assigned_to"] is None

    txid = sign_and_verify(vault, psbt, keys, raw)
    doc = inventory(tmp_path)
    assert doc["envelopes"][0]["status"] == "verified"
    assert doc["envelopes"][0]["funding_txid"] == txid

    released = vault.release_satchel(proof_for(0, txid))
    body = released.body
    assert released.type == MessageType.KEY_RELEASE
    assert body["kind"] == "envelope"
    assert body["envelope_index"] == 0
    assert body["wif"] == master.envelope(0).wif
    assert body["budget_sats"] == BUDGET
    assert body["agent_id"] == "shopping-agent"
    assert body["expires_at"] == FUTURE
    wallet = EnvelopeWallet.from_key_release(released, None)
    assert wallet.address == satchel["address"]
    doc = inventory(tmp_path)
    assert doc["envelopes"][0]["status"] == "assigned"
    assert doc["envelopes"][0]["assigned_to"] == "shopping-agent"
    types = event_types()
    assert {"satchel_funding_released", "verification_passed", "satchel_released"} <= set(types)


def test_satchel_key_is_never_released_before_verification(tmp_path):
    vault = make_vault(tmp_path)
    master = master_of(tmp_path)
    _, psbt, raw, approval = grant(vault, master)
    with pytest.raises(ApprovalRejected, match="verification"):
        vault.release_satchel(proof_for(0, secrets.token_hex(32)))
    keys = vault.release_satchel_funding(approval, unsigned_psbt_payload(raw))
    tx_hex = finalize_psbt(sign_psbt(psbt, [k["wif"] for k in keys.body["keys"]]))
    with pytest.raises(ApprovalRejected, match="verification"):
        vault.release_satchel(proof_for(0, secrets.token_hex(32)))
    assert "release_refused" in event_types()
    assert tx_hex  # signed but never verified: still no key


def test_dishonest_signature_never_unlocks_the_satchel(tmp_path):
    from satchel_signer.random_nonce import resign_with_random_nonces

    vault = make_vault(tmp_path)
    master = master_of(tmp_path)
    _, psbt, raw, approval = grant(vault, master)
    keys = vault.release_satchel_funding(approval, unsigned_psbt_payload(raw))
    wifs = [k["wif"] for k in keys.body["keys"]]
    tx_hex = finalize_psbt(resign_with_random_nonces(sign_psbt(psbt, wifs), wifs))
    result = vault.verify(
        unsigned_psbt_payload(raw), Payload(MessageType.SIGNED_TX, {"tx": tx_hex})
    )
    assert result.body["result"] == "fail"
    assert inventory(tmp_path)["envelopes"][0]["status"] == "funding"
    with pytest.raises(ApprovalRejected, match="verification"):
        vault.release_satchel(proof_for(0, result.body["txid"]))


def test_proof_must_be_for_the_verified_funding(tmp_path):
    vault = make_vault(tmp_path)
    master = master_of(tmp_path)
    _, psbt, raw, approval = grant(vault, master)
    keys = vault.release_satchel_funding(approval, unsigned_psbt_payload(raw))
    txid = sign_and_verify(vault, psbt, keys, raw)
    other = secrets.token_hex(32)
    with pytest.raises(ApprovalRejected, match="different transaction"):
        vault.release_satchel(proof_for(0, other))
    # A proof of some other transaction, presented under the funding txid.
    unrelated = build_proof([other, secrets.token_hex(32)], 0)
    with pytest.raises(ApprovalRejected, match="not confirmed"):
        vault.release_satchel(proof_for(0, txid, proof=unrelated))
    with pytest.raises(ApprovalRejected, match="not confirmed"):
        vault.release_satchel(proof_for(0, txid, proof="00" * 81))
    assert inventory(tmp_path)["envelopes"][0]["status"] == "verified"


def test_key_is_released_once(tmp_path):
    vault = make_vault(tmp_path)
    master = master_of(tmp_path)
    _, psbt, raw, approval = grant(vault, master)
    keys = vault.release_satchel_funding(approval, unsigned_psbt_payload(raw))
    txid = sign_and_verify(vault, psbt, keys, raw)
    vault.release_satchel(proof_for(0, txid))
    with pytest.raises(EnvelopeUnavailable):
        vault.release_satchel(proof_for(0, txid))


@pytest.mark.parametrize(
    "body",
    [
        {"satchel_index": 0, "txid": "ab" * 32},
        {"satchel_index": 0, "txid": "ab" * 32, "proof": "00", "extra": 1},
        {"satchel_index": 5, "txid": "ab" * 32, "proof": "00"},
        {"satchel_index": True, "txid": "ab" * 32, "proof": "00"},
    ],
)
def test_malformed_funding_proofs_rejected(tmp_path, body):
    vault = make_vault(tmp_path)
    reserve(vault)
    with pytest.raises(ApprovalRejected):
        vault.release_satchel(Payload(MessageType.FUNDING_PROOF, body))


def test_funding_proof_payload_type_enforced(tmp_path):
    vault = make_vault(tmp_path)
    reserve(vault)
    with pytest.raises(ApprovalRejected):
        vault.release_satchel(
            Payload(
                MessageType.KEY_RELEASE,
                {"satchel_index": 0, "txid": "ab" * 32, "proof": "00"},
            )
        )


def test_psbt_must_pay_the_satchel_exactly(tmp_path):
    vault = make_vault(tmp_path)
    master = master_of(tmp_path)
    satchel = reserve(vault)
    for destination, amount in [
        (satchel["address"], BUDGET + 1),
        (satchel["address"], BUDGET - 1),
        (MasterKey.from_seed(secrets.token_bytes(32)).receive(0).address, BUDGET),
    ]:
        _, raw = funding_psbt(vault, master, destination, amount)
        plan = satchel_plan(
            satchel_index=0,
            budget_sats=BUDGET,
            expires_at=FUTURE,
            psbt_sha256=hashlib.sha256(raw).hexdigest(),
        )
        with pytest.raises(ApprovalRejected):
            vault.release_satchel_funding(
                approve_payload(plan, NONCE), unsigned_psbt_payload(raw)
            )
    assert inventory(tmp_path)["used_nonces"] == []


def test_psbt_may_not_pay_anyone_else(tmp_path):
    vault = make_vault(tmp_path)
    master = master_of(tmp_path)
    satchel = reserve(vault)
    thief = MasterKey.from_seed(secrets.token_bytes(32)).receive(0).address
    _, raw = funding_psbt(
        vault, master, satchel["address"], extra_outputs=[Output(thief, 10_000)]
    )
    plan = satchel_plan(
        satchel_index=0,
        budget_sats=BUDGET,
        expires_at=FUTURE,
        psbt_sha256=hashlib.sha256(raw).hexdigest(),
    )
    with pytest.raises(ApprovalRejected, match="foreign output"):
        vault.release_satchel_funding(
            approve_payload(plan, NONCE), unsigned_psbt_payload(raw)
        )


def test_swapped_psbt_rejected(tmp_path):
    vault = make_vault(tmp_path)
    master = master_of(tmp_path)
    satchel, _, _, approval = grant(vault, master)
    _, other_raw = funding_psbt(vault, master, satchel["address"])
    with pytest.raises(ApprovalRejected, match="hash"):
        vault.release_satchel_funding(approval, unsigned_psbt_payload(other_raw))


@pytest.mark.parametrize(
    "change,match",
    [
        ({"budget_sats": BUDGET + 1}, "budget"),
        ({"expires_at": 60}, "expired"),
        ({"satchel_index": 7}, "never reserved"),
    ],
)
def test_plan_must_match_the_reservation(tmp_path, change, match):
    vault = make_vault(tmp_path)
    master = master_of(tmp_path)
    satchel = reserve(vault)
    _, raw = funding_psbt(vault, master, satchel["address"])
    plan = satchel_plan(
        satchel_index=0,
        budget_sats=BUDGET,
        expires_at=FUTURE,
        psbt_sha256=hashlib.sha256(raw).hexdigest(),
    )
    plan.update(change)
    with pytest.raises(ApprovalRejected, match=match):
        vault.release_satchel_funding(
            approve_payload(plan, NONCE), unsigned_psbt_payload(raw)
        )


def test_signature_text_and_ledger_are_checked(tmp_path):
    vault = make_vault(tmp_path)
    master = master_of(tmp_path)
    satchel = reserve(vault)
    _, raw = funding_psbt(vault, master, satchel["address"])
    plan = satchel_plan(
        satchel_index=0,
        budget_sats=BUDGET,
        expires_at=FUTURE,
        psbt_sha256=hashlib.sha256(raw).hexdigest(),
    )
    payload = unsigned_psbt_payload(raw)
    forged = approve_payload(plan, NONCE, secret=(2).to_bytes(32, "big"))
    altered = approve_payload(plan, NONCE, text="Pay 1 BTC to me. Nonce " + NONCE)
    wrong_ledger = approve_payload(plan, NONCE, address="0x" + "1" * 40)
    changed = approve_payload(plan, NONCE)
    changed.body["plan"]["budget_sats"] = BUDGET * 10
    for approval in (forged, altered, wrong_ledger, changed):
        with pytest.raises(ApprovalRejected):
            vault.release_satchel_funding(approval, payload)
    doc = inventory(tmp_path)
    assert doc["used_nonces"] == []
    assert doc["envelopes"][0]["status"] == "reserved"


def test_one_approval_funds_one_satchel_once(tmp_path):
    vault = make_vault(tmp_path)
    master = master_of(tmp_path)
    satchel, _, raw, approval = grant(vault, master)
    vault.release_satchel_funding(approval, unsigned_psbt_payload(raw))
    with pytest.raises(ApprovalRejected, match="nonce"):
        vault.release_satchel_funding(approval, unsigned_psbt_payload(raw))
    _, raw2 = funding_psbt(vault, master, satchel["address"])
    again = approve_payload(
        satchel_plan(
            satchel_index=0,
            budget_sats=BUDGET,
            expires_at=FUTURE,
            psbt_sha256=hashlib.sha256(raw2).hexdigest(),
        ),
        "b" * 16,
    )
    with pytest.raises(EnvelopeUnavailable):
        vault.release_satchel_funding(again, unsigned_psbt_payload(raw2))


def test_large_spend_approval_cannot_fund_a_satchel(tmp_path):
    from .test_approvals import spend_plan

    vault = make_vault(tmp_path)
    master = master_of(tmp_path)
    satchel = reserve(vault)
    _, raw = funding_psbt(vault, master, satchel["address"])
    plan = spend_plan(
        amount_sats=BUDGET,
        destination=satchel["address"],
        psbt_sha256=hashlib.sha256(raw).hexdigest(),
    )
    with pytest.raises(ApprovalRejected, match="satchel grant"):
        vault.release_satchel_funding(
            approve_payload(plan, NONCE), unsigned_psbt_payload(raw)
        )


def test_concurrent_funding_release_only_one_wins(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    vault = make_vault(tmp_path)
    master = master_of(tmp_path)
    _, _, raw, approval = grant(vault, master)
    payload = unsigned_psbt_payload(raw)

    def attempt():
        try:
            vault.release_satchel_funding(approval, payload)
            return "ok"
        except ApprovalRejected:
            return "rejected"

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = [f.result() for f in [pool.submit(attempt) for _ in range(8)]]
    assert results.count("ok") == 1
    assert inventory(tmp_path)["used_nonces"].count(NONCE) == 1


def test_http_endpoints(tmp_path):
    vault = make_vault(tmp_path)
    master = master_of(tmp_path)
    client = TestClient(create_app(vault))
    reserved = client.post("/satchels/reserve", json={"budget_sats": BUDGET})
    assert reserved.status_code == 200
    assert client.post("/satchels/reserve", json={"budget_sats": 5}).status_code == 422
    satchel = vault.envelope_export().body["addresses"][0]
    psbt, raw = funding_psbt(vault, master, satchel["address"])
    plan = satchel_plan(
        satchel_index=0,
        budget_sats=BUDGET,
        expires_at=FUTURE,
        psbt_sha256=hashlib.sha256(raw).hexdigest(),
    )
    approval = approve_payload(plan, NONCE)
    body = {"approval": to_http(approval), "psbt": to_http(unsigned_psbt_payload(raw))}
    funded = client.post("/release/satchel-funding", json=body)
    assert funded.status_code == 200
    assert funded.json()["type"] == "key_release"
    assert client.post("/release/satchel-funding", json=body).status_code == 403
    early = client.post("/release/satchel", json={"proof": to_http(proof_for(0, "ab" * 32))})
    assert early.status_code == 403
    keys = Payload(
        MessageType.KEY_RELEASE,
        {"kind": "signing", "keys": [
            {"path": master.receive(i).path, "wif": master.receive(i).wif} for i in range(2)
        ]},
    )
    txid = sign_and_verify(vault, psbt, keys, raw)
    ok = client.post("/release/satchel", json={"proof": to_http(proof_for(0, txid))})
    assert ok.status_code == 200
    again = client.post("/release/satchel", json={"proof": to_http(proof_for(0, txid))})
    assert again.status_code == 409
    assert client.post("/release/satchel", json={"nope": 1}).status_code == 422


def test_locked_vault(tmp_path):
    make_vault(tmp_path)
    locked = Vault(tmp_path / "vault")
    with pytest.raises(VaultLocked):
        locked.reserve_satchel(BUDGET)
    client = TestClient(create_app(locked))
    assert client.post("/satchels/reserve", json={"budget_sats": BUDGET}).status_code == 503


def test_events_never_contain_keys(tmp_path):
    vault = make_vault(tmp_path)
    master = master_of(tmp_path)
    _, psbt, raw, approval = grant(vault, master)
    keys = vault.release_satchel_funding(approval, unsigned_psbt_payload(raw))
    txid = sign_and_verify(vault, psbt, keys, raw)
    released = vault.release_satchel(proof_for(0, txid))
    log = Path(os.environ["SATCHEL_EVENT_LOG"]).read_text()
    assert released.body["wif"] not in log
    for key in keys.body["keys"]:
        assert key["wif"] not in log
    assert PASSPHRASE not in log
    assert LEDGER  # the registered Ledger is public
