"""ToolBox behaviour against stub marketplace/laptop clients."""

import json
import os
from pathlib import Path

import pytest

from satchel_agent.tools import ToolBox, UNTRUSTED_NOTE, _sanitise_purpose
from satchel_core.keys import MasterKey
from satchel_core.payloads import MessageType, Payload, to_http

SEED = bytes.fromhex("000102030405060708090a0b0c0d0e0f")
MASTER = MasterKey.from_seed(SEED)
PRODUCT = {
    "id": "aurora-anc-wireless-headphones",
    "name": "Aurora ANC Wireless Headphones",
    "category": "headphones",
    "description": "Untrusted listing text.",
    "seller": "Aurora Audio",
    "price_sats": 179_000,
    "price_btc": "0.00179",
    "price_usd": 179,
    "stock": 12,
    "delivery_days": 1,
    "delivery_date": "2026-10-13",
    "available": 12,
}


class StubNode:
    def list_unspent(self, addresses):
        return []

    def is_unspent(self, txid, vout, include_mempool=True):
        return False


class StubMarketplace:
    def __init__(self):
        self.checkout_calls = []
        self.orders = {}

    def search(self, query, **params):
        self.search_params = params
        return {
            "today": "2026-10-12",
            "usd_per_btc": 100_000,
            "count": 1,
            "results": [PRODUCT],
        }

    def product(self, product_id):
        return dict(PRODUCT)

    def checkout(self, product_id, quantity):
        self.checkout_calls.append((product_id, quantity))
        order = {
            "order_id": "ab" * 16,
            "product_id": product_id,
            "name": PRODUCT["name"],
            "quantity": quantity,
            "amount_sats": PRODUCT["price_sats"] * quantity,
            "amount_usd": PRODUCT["price_usd"] * quantity,
            "amount_btc": "0.00179",
            "pay_to": "bcrt1qmerchantorder",
            "status": "awaiting_payment",
            "delivery_date": "2026-10-13",
            "txids": [],
        }
        self.orders[order["order_id"]] = order
        return order

    def order(self, order_id):
        order = self.orders[order_id]
        return {**order, "status": self.orders[order_id].get("status")}

    def rate(self):
        return {"usd_per_btc": 100_000}


class StubLaptop:
    def __init__(self, grant_response=None, spend_response=None):
        self.grant_response = grant_response
        self.spend_response = spend_response or {
            "broadcast": True,
            "txid": "cc" * 32,
            "stage": "broadcast",
            "reason": None,
            "failures": [],
        }
        self.grant_calls = []
        self.spend_calls = []

    def grant(self, agent_id, budget_sats, demo_auto=None):
        self.grant_calls.append(
            {"agent_id": agent_id, "budget_sats": budget_sats}
        )
        return self.grant_response

    def spend(self, destination, amount_sats, purpose, demo_auto=None):
        self.spend_calls.append(
            {
                "destination": destination,
                "amount_sats": amount_sats,
                "purpose": purpose,
                "demo_auto": demo_auto,
            }
        )
        return self.spend_response


def key_release(index=0, budget=200_000):
    key = MASTER.envelope(index)
    return to_http(
        Payload(
            MessageType.KEY_RELEASE,
            {
                "kind": "envelope",
                "envelope_index": index,
                "path": key.path,
                "address": key.address,
                "public_key": key.public_key,
                "wif": key.wif,
                "budget_sats": budget,
                "agent_id": "shopper-1",
                "expires_at": 1_900_000_000,
            },
        )
    )


class StubWallet:
    def __init__(self, spendable=200_000, pending=0, max_payable=199_000):
        self._spendable = spendable
        self._pending = pending
        self._max = max_payable
        self.budget_sats = 200_000
        self.expires_at = 1_900_000_000
        self.pay_calls = []

    def balance_sats(self):
        return self._spendable

    def pending_change_sats(self):
        return self._pending

    def max_payable_sats(self, address):
        return self._max

    def pay(self, address, amount):
        self.pay_calls.append((address, amount))
        self._spendable = max(0, self._spendable - amount - 500)
        return "dd" * 32


def toolbox(tmp_path, **kwargs):
    kwargs.setdefault("marketplace", StubMarketplace())
    kwargs.setdefault("laptop", StubLaptop())
    kwargs.setdefault("node", StubNode())
    return ToolBox(agent_id="shopper-test01", session_id="sess1", **kwargs)


def test_unknown_tool_and_bad_input(tmp_path):
    box = toolbox(tmp_path)
    assert "error" in box.run("launch_rocket", {})
    assert "error" in box.run("search_products", "not-a-dict")


def test_search_wraps_listings_with_untrusted_note(tmp_path):
    box = toolbox(tmp_path)
    result = box.run(
        "search_products",
        {"query": "headphones", "max_price_usd": 200, "deliver_by": "2026-10-16"},
    )
    assert result["note"] == UNTRUSTED_NOTE
    assert result["count"] == 1
    assert result["results"][0]["listing"]["id"] == PRODUCT["id"]
    assert box.marketplace.search_params["max_price_usd"] == 200


def test_product_details_note(tmp_path):
    box = toolbox(tmp_path)
    result = box.run("get_product_details", {"product_id": PRODUCT["id"]})
    assert result["note"] == UNTRUSTED_NOTE
    assert result["listing"]["seller"] == "Aurora Audio"


def test_check_budget_without_wallet(tmp_path):
    box = toolbox(tmp_path)
    assert box.run("check_budget", {}) == {"has_budget": False}


def test_check_budget_with_wallet(tmp_path):
    box = toolbox(tmp_path)
    box.wallet = StubWallet(spendable=150_000, pending=20_000)
    result = box.run("check_budget", {})
    assert result["has_budget"] is True
    assert result["budget_sats"] == 200_000
    assert result["budget_usd"] == 200
    assert result["spendable_sats"] == 150_000
    assert result["pending_change_sats"] == 20_000
    assert result["remaining_sats"] == 170_000
    assert result["remaining_usd"] == 170
    assert result["expires_at"] == 1_900_000_000


def test_request_budget_converts_usd_and_stores_wallet(tmp_path):
    laptop = StubLaptop(
        grant_response={
            "granted": True,
            "budget_sats": 200_000,
            "envelope_index": 2,
            "key_release": key_release(),
        }
    )
    box = toolbox(tmp_path, laptop=laptop)
    result = box.run("request_budget", {"amount_usd": 199.5})
    assert result["granted"] is True
    assert result["budget_sats"] == 200_000
    assert result["envelope_index"] == 2
    assert laptop.grant_calls[0]["budget_sats"] == 199_500
    assert box.wallet is not None
    assert box.wallet.expires_at == 1_900_000_000
    second = box.run("request_budget", {"amount_usd": 10})
    assert second["granted"] is True
    assert box.wallet is not None


def test_request_budget_rejection_leaves_no_wallet(tmp_path):
    laptop = StubLaptop(
        grant_response={"granted": False, "reason": "rejected on the Ledger"}
    )
    box = toolbox(tmp_path, laptop=laptop)
    result = box.run("request_budget", {"amount_usd": 200})
    assert result == {"granted": False, "reason": "rejected on the Ledger"}
    assert box.wallet is None


def test_buy_without_budget_makes_no_order(tmp_path):
    market = StubMarketplace()
    box = toolbox(tmp_path, marketplace=market)
    result = box.run("buy_product", {"product_id": PRODUCT["id"]})
    assert "no budget" in result["error"]
    assert market.checkout_calls == []


def test_exceeds_budget_pays_nothing(tmp_path):
    market = StubMarketplace()
    box = toolbox(tmp_path, marketplace=market)
    box.wallet = StubWallet(spendable=50_000, pending=0, max_payable=49_500)
    result = box.run("buy_product", {"product_id": PRODUCT["id"]})
    assert result["status"] == "exceeds_budget"
    assert result["order_id"] == "ab" * 16
    assert result["amount_sats"] == 179_000
    assert result["remaining_sats"] == 50_000
    assert box.wallet.pay_calls == []


def test_paid_path_pays_exact_order_amount(tmp_path):
    market = StubMarketplace()
    box = toolbox(tmp_path, marketplace=market)
    box.wallet = StubWallet(spendable=200_000, pending=0, max_payable=199_000)
    result = box.run("buy_product", {"product_id": PRODUCT["id"]})
    assert result["status"] == "paid_from_budget"
    assert box.wallet.pay_calls == [("bcrt1qmerchantorder", 179_000)]
    assert result["amount_sats"] == 179_000
    assert result["txid"] == "dd" * 32
    assert result["delivery_date"] == "2026-10-13"
    assert result["remaining_sats"] == 20_500


def test_check_order(tmp_path):
    market = StubMarketplace()
    box = toolbox(tmp_path, marketplace=market)
    order = market.checkout(PRODUCT["id"], 1)
    result = box.run("check_order", {"order_id": order["order_id"]})
    assert result["status"] == "awaiting_payment"
    assert result["amount_sats"] == 179_000
    assert result["delivery_date"] == "2026-10-13"


def test_large_purchase_uses_order_fields(tmp_path):
    market = StubMarketplace()
    laptop = StubLaptop()
    box = toolbox(tmp_path, marketplace=market, laptop=laptop)
    order = market.checkout(PRODUCT["id"], 1)
    result = box.run(
        "request_large_purchase",
        {"order_id": order["order_id"], "purpose": "Aurora!!! 🎧   nice"},
    )
    assert result["paid"] is True
    assert result["txid"] == "cc" * 32
    call = laptop.spend_calls[0]
    assert call["destination"] == "bcrt1qmerchantorder"
    assert call["amount_sats"] == 179_000
    assert call["purpose"] == "Aurora nice"


def test_large_purchase_rejects_non_awaiting_order(tmp_path):
    market = StubMarketplace()
    box = toolbox(tmp_path, marketplace=market)
    order = market.checkout(PRODUCT["id"], 1)
    market.orders[order["order_id"]]["status"] = "paid"
    result = box.run("request_large_purchase", {"order_id": order["order_id"]})
    assert "error" in result


def test_purpose_sanitisation():
    assert _sanitise_purpose("Aurora headphones!") == "Aurora headphones"
    assert _sanitise_purpose("") == "purchase"
    assert _sanitise_purpose(None) == "purchase"
    assert _sanitise_purpose("!!!") == "purchase"
    assert len(_sanitise_purpose("x" * 100)) <= 32
    assert _sanitise_purpose("a" * 40) == "a" * 32


def test_tool_events_have_no_wif(tmp_path):
    market = StubMarketplace()
    laptop = StubLaptop(
        grant_response={
            "granted": True,
            "budget_sats": 200_000,
            "envelope_index": 0,
            "key_release": key_release(),
        }
    )
    box = toolbox(tmp_path, marketplace=market, laptop=laptop)
    box.run("request_budget", {"amount_usd": 200})
    box.run("buy_product", {"product_id": PRODUCT["id"]})
    events = Path(os.environ["SATCHEL_EVENT_LOG"]).read_text()
    assert '"tool_call"' in events and '"tool_result"' in events
    assert MASTER.envelope(0).wif not in events
    for line in events.splitlines():
        event = json.loads(line)
        if event["component"] == "agent" and event["type"] == "tool_call":
            assert "session_id" in event["payload"]
            assert "agent_id" in event["payload"]
