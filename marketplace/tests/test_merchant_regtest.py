"""End-to-end marketplace payments against real regtest wallets."""

from datetime import date

import pytest

from satchel_agent.wallet import EnvelopeWallet
from satchel_core.keys import MasterKey
from satchel_core.payloads import MessageType, Payload
from satchel_core.regtest import COIN
from satchel_marketplace.catalogue import Catalogue
from satchel_marketplace.merchant import MerchantWallet
from satchel_marketplace.store import Store

SEED = bytes.fromhex("000102030405060708090a0b0c0d0e0f")
MASTER = MasterKey.from_seed(SEED)

pytestmark = pytest.mark.regtest


@pytest.fixture
def merchant(node):
    wallet = MerchantWallet(node)
    wallet.ensure()
    return wallet


@pytest.fixture
def store(merchant, tmp_path):
    return Store(
        Catalogue.load(),
        merchant,
        data_dir=tmp_path / "marketplace",
        clock=lambda: date.today(),
    )


def test_checkout_address_is_merchants(node, merchant, store):
    order = store.checkout("digital-kitchen-scale")
    info = node.call(
        "getaddressinfo", order["pay_to"], wallet=merchant.name
    )
    assert info["ismine"] is True
    assert order["pay_to"].startswith("bcrt1")


def test_faucet_payment_lifecycle(node, merchant, store):
    order = store.checkout("digital-kitchen-scale")
    assert store.status(order["order_id"])["status"] == "awaiting_payment"
    txid = node.send_to_address(order["pay_to"], order["amount_sats"])
    assert (
        store.status(order["order_id"])["status"] == "payment_pending"
    )
    node.mine_blocks(1, node.faucet_address())
    current = store.status(order["order_id"])
    assert current["status"] == "paid"
    assert txid in current["txids"]
    assert current["paid_at"]


def test_underpayment_stays_underpaid(node, merchant, store):
    order = store.checkout("chefs-knife-20cm")
    node.send_to_address(order["pay_to"], order["amount_sats"] - 1)
    node.mine_blocks(1, node.faucet_address())
    current = store.status(order["order_id"])
    assert current["status"] == "underpaid"
    assert current["received_sats"] == order["amount_sats"] - 1


def test_envelope_wallet_pays_order(node, merchant, store):
    order = store.checkout("aurora-anc-wireless-headphones")
    key = MASTER.envelope(0)
    node.ensure_faucet(order["amount_sats"] + COIN)
    node.fund_address(key.address, order["amount_sats"] + 5_000)
    release = Payload(
        MessageType.KEY_RELEASE,
        {
            "kind": "envelope",
            "envelope_index": 0,
            "path": key.path,
            "address": key.address,
            "public_key": key.public_key,
            "wif": key.wif,
            "budget_sats": order["amount_sats"] + 5_000,
            "agent_id": "test-shopper",
            "expires_at": 1_900_000_000,
        },
    )
    wallet = EnvelopeWallet.from_key_release(release, node)
    txid = wallet.pay(order["pay_to"], order["amount_sats"])
    assert store.status(order["order_id"])["status"] == "payment_pending"
    node.mine_blocks(1, node.faucet_address())
    current = store.status(order["order_id"])
    assert current["status"] == "paid"
    assert txid in current["txids"]
