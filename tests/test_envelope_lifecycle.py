"""Envelope lifecycle: agent payments drive laptop status transitions."""

import secrets

import pytest

from satchel_agent.wallet import EnvelopeWallet
from satchel_core.keys import MasterKey
from satchel_core.payloads import MessageType, Payload
from satchel_laptop.envelopes import envelope_statuses
from satchel_laptop.state import LaptopState


@pytest.mark.regtest
def test_laptop_status_transitions(node, tmp_path):
    master = MasterKey.from_seed(secrets.token_bytes(32))
    key = master.envelope(0)
    node.fund_address(key.address, 100_000)
    utxo = node.list_unspent([key.address])[0]
    release = Payload(
        MessageType.KEY_RELEASE,
        {
            "envelope_index": 0,
            "path": key.path,
            "address": key.address,
            "public_key": key.public_key,
            "wif": key.wif,
            "budget_sats": 100_000,
            "agent_id": "agent-1",
        },
    )
    wallet = EnvelopeWallet.from_key_release(release, node)
    fresh = MasterKey.from_seed(secrets.token_bytes(32)).receive(0).address
    export = Payload(
        MessageType.ADDRESS_EXPORT,
        {
            "kind": "envelope",
            "fingerprint": master.fingerprint,
            "addresses": [
                {
                    "index": 0,
                    "path": key.path,
                    "address": key.address,
                    "public_key": key.public_key,
                    "budget_sats": 100_000,
                    "assigned_to": "agent-1",
                }
            ],
        },
    )
    state = LaptopState(tmp_path / "state.json")
    state.record_funding(key.address, utxo.txid, utxo.vout, 100_000)
    assert envelope_statuses(export, node, state)[0].status == "assigned"
    wallet.pay(fresh, 30_000)
    node.mine_blocks(1, node.faucet_address())
    assert envelope_statuses(export, node, state)[0].status == "spent"
    wallet.pay(fresh, wallet.max_payable_sats(fresh))
    node.mine_blocks(1, node.faucet_address())
    assert envelope_statuses(export, node, state)[0].status == "drained"
