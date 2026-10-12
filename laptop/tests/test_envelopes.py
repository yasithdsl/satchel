"""Envelope status rules against a stub node."""

import pytest
from embit import bip32
from embit.networks import NETWORKS

from satchel_core.keys import MasterKey
from satchel_core.payloads import MessageType, Payload
from satchel_core.regtest import Utxo
from satchel_laptop.envelopes import envelope_statuses
from satchel_laptop.state import LaptopState

SEED = bytes.fromhex("000102030405060708090a0b0c0d0e0f")
MASTER = MasterKey.from_seed(SEED)


class StubNode:
    def __init__(self, utxos=()):
        self.utxos = list(utxos)
        self.list_unspent_calls = []

    def list_unspent(self, addresses):
        self.list_unspent_calls.append(list(addresses))
        return [u for u in self.utxos if u.address in set(addresses)]


def utxo(address, amount=50_000, txid=None, vout=0):
    return Utxo(
        txid=txid or "aa" * 32,
        vout=vout,
        address=address,
        amount_sats=amount,
        script_pubkey="0014" + "ab" * 20,
        height=100,
        coinbase=False,
    )


def export_payload(count=5, assigned=(), budget=50_000):
    addresses = []
    for i in range(count):
        key = MASTER.envelope(i)
        addresses.append(
            {
                "index": i,
                "path": key.path,
                "address": key.address,
                "public_key": key.public_key,
                "budget_sats": budget,
                "assigned_to": f"agent-{i}" if i in assigned else None,
            }
        )
    return Payload(
        MessageType.ADDRESS_EXPORT,
        {"kind": "envelope", "fingerprint": MASTER.fingerprint, "addresses": addresses},
    )


def test_all_five_statuses(tmp_path):
    payload = export_payload(assigned=(3,))
    addrs = [a["address"] for a in payload.body["addresses"]]
    state = LaptopState(tmp_path / "s.json")
    state.record_funding(addrs[1], "bb" * 32, 0, 50_000)          # drained
    state.record_funding(addrs[2], "cc" * 32, 0, 50_000)          # spent
    state.record_funding(addrs[3], "dd" * 32, 0, 50_000)          # assigned
    node = StubNode(
        utxos=[
            utxo(addrs[2], txid="ee" * 32),                        # different outpoint
            utxo(addrs[3], txid="dd" * 32, vout=0),
            utxo(addrs[4], txid="ff" * 32),
        ]
    )
    statuses = envelope_statuses(payload, node, state)
    assert [s.status for s in statuses] == [
        "unfunded",
        "drained",
        "spent",
        "assigned",
        "unassigned",
    ]
    assert len(node.list_unspent_calls) == 1
    spent = statuses[2]
    assert spent.balance_sats == 50_000
    assert spent.utxo_count == 1


def test_bad_payload_rejected(tmp_path):
    state = LaptopState(tmp_path / "s.json")
    node = StubNode()
    with pytest.raises(ValueError):
        envelope_statuses(
            Payload(MessageType.SPEND_PLAN, {}), node, state
        )
    wrong_kind = Payload(
        MessageType.ADDRESS_EXPORT,
        {"kind": "receive", "fingerprint": "x", "addresses": []},
    )
    with pytest.raises(ValueError):
        envelope_statuses(wrong_kind, node, state)


def test_address_pubkey_mismatch_rejected(tmp_path):
    payload = export_payload(count=1)
    payload.body["addresses"][0]["address"] = MASTER.envelope(1).address
    with pytest.raises(ValueError):
        envelope_statuses(payload, StubNode(), LaptopState(tmp_path / "s.json"))
