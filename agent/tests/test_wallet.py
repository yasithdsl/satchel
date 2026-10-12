"""EnvelopeWallet tests: payload validation offline, spending on regtest."""

import json
import math
import os
import secrets
from pathlib import Path

import pytest
from embit import script
from embit.transaction import Transaction

from satchel_agent.wallet import EnvelopeWallet, InsufficientFunds
from satchel_core.keys import NETWORK, MasterKey
from satchel_core.payloads import MessageType, Payload
from satchel_core.regtest import RPCError, Utxo
from satchel_core.signing import sign_digest
from satchel_core.transactions import (
    Output,
    SpendInput,
    build_psbt,
    extract_signatures,
    input_sighashes,
)


def release_payload(master, index=0, budget=100_000, **overrides):
    key = master.envelope(index)
    body = {
        "envelope_index": index,
        "path": key.path,
        "address": key.address,
        "public_key": key.public_key,
        "wif": key.wif,
        "budget_sats": budget,
        "agent_id": "agent-1",
    }
    body.update(overrides)
    return Payload(MessageType.KEY_RELEASE, body)


def event_log() -> str:
    return Path(os.environ["SATCHEL_EVENT_LOG"]).read_text()


def event_types() -> list[str]:
    return [json.loads(line)["type"] for line in event_log().splitlines()]


@pytest.fixture
def funded(node):
    master = MasterKey.from_seed(secrets.token_bytes(32))
    key = master.envelope(0)
    node.fund_address(key.address, 100_000)
    utxo = node.list_unspent([key.address])[0]
    wallet = EnvelopeWallet.from_key_release(release_payload(master), node)
    return {
        "wallet": wallet,
        "master": master,
        "key": key,
        "fund_txid": utxo.txid,
        "fund_vout": utxo.vout,
    }


@pytest.fixture
def fresh_address():
    return MasterKey.from_seed(secrets.token_bytes(32)).receive(0).address


def test_rejects_wrong_message_type():
    master = MasterKey.from_seed(secrets.token_bytes(32))
    payload = Payload(MessageType.SPEND_PLAN, release_payload(master).body)
    with pytest.raises(ValueError):
        EnvelopeWallet.from_key_release(payload, None)


def test_rejects_receive_branch_path():
    master = MasterKey.from_seed(secrets.token_bytes(32))
    payload = release_payload(master, path=master.receive(0).path)
    with pytest.raises(ValueError):
        EnvelopeWallet.from_key_release(payload, None)


def test_rejects_index_path_mismatch():
    master = MasterKey.from_seed(secrets.token_bytes(32))
    payload = release_payload(master, envelope_index=7)
    with pytest.raises(ValueError):
        EnvelopeWallet.from_key_release(payload, None)


def test_rejects_wif_pubkey_mismatch():
    master = MasterKey.from_seed(secrets.token_bytes(32))
    payload = release_payload(master, wif=master.envelope(1).wif)
    with pytest.raises(ValueError):
        EnvelopeWallet.from_key_release(payload, None)


def test_rejects_address_mismatch():
    master = MasterKey.from_seed(secrets.token_bytes(32))
    payload = release_payload(master, address=master.envelope(1).address)
    with pytest.raises(ValueError):
        EnvelopeWallet.from_key_release(payload, None)


@pytest.mark.parametrize(
    "missing",
    ["envelope_index", "path", "address", "public_key", "wif", "budget_sats", "agent_id"],
)
def test_rejects_missing_field(missing):
    master = MasterKey.from_seed(secrets.token_bytes(32))
    body = release_payload(master).body
    del body[missing]
    with pytest.raises(ValueError):
        EnvelopeWallet.from_key_release(
            Payload(MessageType.KEY_RELEASE, body), None
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("envelope_index", "0"),
        ("envelope_index", True),
        ("path", 7),
        ("address", None),
        ("public_key", b"bytes"),
        ("wif", 42),
        ("budget_sats", "50000"),
        ("agent_id", 9),
    ],
)
def test_rejects_mistyped_field(field, value):
    master = MasterKey.from_seed(secrets.token_bytes(32))
    payload = release_payload(master, **{field: value})
    with pytest.raises(ValueError):
        EnvelopeWallet.from_key_release(payload, None)


def test_repr_hides_wif():
    master = MasterKey.from_seed(secrets.token_bytes(32))
    wallet = EnvelopeWallet.from_key_release(release_payload(master), None)
    assert master.envelope(0).wif not in repr(wallet)
    assert "wif" not in repr(wallet)


@pytest.mark.regtest
def test_normal_payment(node, funded, fresh_address):
    wallet = funded["wallet"]
    before = wallet.spendable_utxos()
    assert wallet.balance_sats() == 100_000
    txid = wallet.pay(fresh_address, 30_000)
    node.mine_blocks(1, node.faucet_address())
    dest_utxos = node.list_unspent([fresh_address])
    assert len(dest_utxos) == 1
    assert dest_utxos[0].amount_sats == 30_000
    raw = node.get_transaction(txid)["hex"]
    tx = Transaction.parse(bytes.fromhex(raw))
    assert len(tx.vout) == 2
    change_script = script.address_to_scriptpubkey(wallet.address)
    assert tx.vout[1].script_pubkey.data == change_script.data
    change_sats = tx.vout[1].value
    fee = 100_000 - 30_000 - change_sats
    assert fee > 0
    assert wallet.balance_sats() == change_sats == 100_000 - 30_000 - fee
    spend_inputs = [
        SpendInput(u.txid, u.vout, u.amount_sats, wallet.public_key)
        for u in before
    ]
    psbt = build_psbt(
        spend_inputs,
        [Output(fresh_address, 30_000)],
        Output(wallet.address, change_sats),
    )
    extracted = extract_signatures(raw, psbt)
    assert len(extracted) == len(before)
    for entry in extracted:
        assert entry.signature == sign_digest(
            funded["key"].wif, entry.sighash
        )
        assert entry.public_key == wallet.public_key
    assert "payment_sent" in event_types()
    assert funded["key"].wif not in event_log()


@pytest.mark.regtest
def test_drain_payment(node, funded, fresh_address):
    wallet = funded["wallet"]
    amount = wallet.max_payable_sats(fresh_address)
    assert amount == 100_000 - 2 * math.ceil(10.5 + 68 + 31)
    txid = wallet.pay(fresh_address, amount)
    tx = Transaction.parse(
        bytes.fromhex(node.get_transaction(txid)["hex"])
    )
    assert len(tx.vout) == 1
    node.mine_blocks(1, node.faucet_address())
    assert wallet.balance_sats() == 0


@pytest.mark.regtest
def test_over_budget_rejected(node, funded, fresh_address):
    wallet = funded["wallet"]
    mempool_before = node.call("getrawmempool")
    utxos_before = node.list_unspent([wallet.address])
    with pytest.raises(InsufficientFunds):
        wallet.pay(fresh_address, wallet.balance_sats() + 1)
    assert node.call("getrawmempool") == mempool_before
    assert node.list_unspent([wallet.address]) == utxos_before
    assert "payment_rejected" in event_types()


@pytest.mark.regtest
def test_second_payment_before_mining_rejected(node, funded, fresh_address):
    wallet = funded["wallet"]
    wallet.pay(fresh_address, 30_000)
    with pytest.raises(InsufficientFunds):
        wallet.pay(fresh_address, 30_000)


@pytest.mark.regtest
def test_rejected_payments_emit_payment_rejected(node, funded, fresh_address):
    wallet = funded["wallet"]
    with pytest.raises(ValueError):
        wallet.pay(fresh_address, 100)
    with pytest.raises(ValueError):
        wallet.pay("bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4", 30_000)
    with pytest.raises(ValueError):
        wallet.pay("not-an-address", 30_000)
    assert event_types().count("payment_rejected") == 3
    last = json.loads(event_log().splitlines()[-1])
    assert last["type"] == "payment_rejected"
    assert last["payload"]["reason"]
    assert funded["key"].wif not in event_log()


@pytest.mark.regtest
def test_broadcast_failure_emits_payment_failed(
    node, funded, fresh_address, monkeypatch
):
    wallet = funded["wallet"]

    def boom(raw):
        raise RPCError(-26, "tx rejected")

    monkeypatch.setattr(wallet.node, "broadcast", boom)
    with pytest.raises(RPCError):
        wallet.pay(fresh_address, 30_000)
    assert "payment_failed" in event_types()


@pytest.mark.regtest
def test_pending_change_reported(node, funded, fresh_address):
    wallet = funded["wallet"]
    assert wallet.pending_change_sats() == 0
    txid = wallet.pay(fresh_address, 30_000)
    raw = node.get_transaction(txid)["hex"]
    tx = Transaction.parse(bytes.fromhex(raw))
    change_sats = tx.vout[1].value
    assert wallet.balance_sats() == 0
    assert wallet.pending_change_sats() == change_sats
    node.mine_blocks(1, node.faucet_address())
    assert wallet.pending_change_sats() == 0
    assert wallet.balance_sats() == change_sats
