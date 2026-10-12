"""Integration tests against the local regtest bitcoind (skipped when it is down)."""

import secrets

import pytest
from embit import ec, script
from embit.networks import NETWORKS

from satchel_core.regtest import FAUCET_WALLET


def fresh_address() -> str:
    private_key = ec.PrivateKey(secrets.token_bytes(32))
    return script.p2wpkh(private_key.get_public_key()).address(NETWORKS["regtest"])


@pytest.mark.regtest
def test_funded_address_appears_unspent(node):
    address = fresh_address()
    assert node.list_unspent([address]) == []
    txid = node.fund_address(address, 150_000)
    utxos = node.list_unspent([address])
    assert len(utxos) == 1
    assert utxos[0].txid == txid
    assert utxos[0].amount_sats == 150_000
    assert utxos[0].address == address
    assert utxos[0].coinbase is False
    assert node.get_transaction(txid)["confirmations"] >= 1


@pytest.mark.regtest
def test_broadcast_raw_transaction(node):
    address = fresh_address()
    raw = node.call(
        "createrawtransaction", [], {address: "0.00100000"}, wallet=FAUCET_WALLET
    )
    funded = node.call("fundrawtransaction", raw, wallet=FAUCET_WALLET)
    signed = node.call(
        "signrawtransactionwithwallet", funded["hex"], wallet=FAUCET_WALLET
    )
    assert signed["complete"] is True
    txid = node.broadcast(signed["hex"])
    expected = node.call("decoderawtransaction", signed["hex"])["txid"]
    assert txid == expected
    tx = node.get_transaction(txid)
    assert tx.get("confirmations", 0) == 0
