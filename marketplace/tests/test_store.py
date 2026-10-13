"""Checkout and payment-status transitions against a stub merchant."""

import json
import os
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from satchel_marketplace.app import create_app
from satchel_marketplace.catalogue import Catalogue
from satchel_marketplace.store import (
    OutOfStock,
    Store,
    UnknownOrder,
    UnknownProduct,
)

PRODUCT = "digital-kitchen-scale"
PRICE = 25_000
STOCK = 50


def store(make_store, tmp_path):
    return make_store(tmp_path, clock=lambda: date(2026, 10, 12))


def test_checkout_shape(make_store, tmp_path, merchant):
    s = store(make_store, tmp_path)
    order = s.checkout(PRODUCT, 2)
    assert order["order_id"] and len(order["order_id"]) == 32
    assert order["product_id"] == PRODUCT
    assert order["quantity"] == 2
    assert order["amount_sats"] == PRICE * 2
    assert order["amount_btc"] == "0.00050000"
    assert order["amount_usd"] == 50
    assert order["pay_to"].startswith("bcrt1")
    assert order["payment_uri"] == f"bitcoin:{order['pay_to']}?amount=0.00050000"
    assert order["status"] == "awaiting_payment"
    assert order["delivery_date"] == "2026-10-13"
    assert order["paid_at"] is None and order["txids"] == []
    assert merchant.new_address


def test_status_transitions(make_store, tmp_path, merchant):
    s = store(make_store, tmp_path)
    order = s.checkout(PRODUCT)
    pay_to = order["pay_to"]
    current = s.status(order["order_id"])
    assert current["status"] == "awaiting_payment"
    assert current["received_sats"] == 0 and current["pending_sats"] == 0
    merchant.seen[pay_to] = PRICE
    current = s.status(order["order_id"])
    assert current["status"] == "payment_pending"
    assert current["pending_sats"] == PRICE
    merchant.confirmed[pay_to] = PRICE
    merchant._txids[pay_to] = ["aa" * 32]
    current = s.status(order["order_id"])
    assert current["status"] == "paid"
    assert current["txids"] == ["aa" * 32]
    assert current["paid_at"]
    merchant.seen[pay_to] = 0
    merchant.confirmed[pay_to] = 0
    assert s.status(order["order_id"])["status"] == "paid"


def test_underpaid(make_store, tmp_path, merchant):
    s = store(make_store, tmp_path)
    order = s.checkout(PRODUCT)
    merchant.confirmed[order["pay_to"]] = PRICE - 1
    current = s.status(order["order_id"])
    assert current["status"] == "underpaid"
    assert current["received_sats"] == PRICE - 1
    merchant.confirmed[order["pay_to"]] = PRICE
    assert s.status(order["order_id"])["status"] == "paid"


def test_unconfirmed_partial_stays_awaiting(make_store, tmp_path, merchant):
    s = store(make_store, tmp_path)
    order = s.checkout(PRODUCT)
    merchant.seen[order["pay_to"]] = PRICE - 1
    assert s.status(order["order_id"])["status"] == "awaiting_payment"


def test_unknown_product_and_order(make_store, tmp_path):
    s = store(make_store, tmp_path)
    with pytest.raises(UnknownProduct):
        s.checkout("nope")
    with pytest.raises(UnknownOrder):
        s.status("0" * 32)


def test_quantity_validation(make_store, tmp_path):
    s = store(make_store, tmp_path)
    for bad in (0, -1, 11, True, 1.5, "2"):
        with pytest.raises(ValueError):
            s.checkout(PRODUCT, bad)


def test_stock_decreases_after_checkout(make_store, tmp_path):
    s = store(make_store, tmp_path)
    assert s.product("halo-pro-anc-headphones")["available"] == 6
    s.checkout("halo-pro-anc-headphones", 2)
    assert s.product("halo-pro-anc-headphones")["available"] == 4
    results = s.search(q="halo", include_out_of_stock=True)["results"]
    assert results[0]["available"] == 4


def test_checkout_over_available_409(make_store, tmp_path):
    s = store(make_store, tmp_path)
    s.checkout("espresso-machine-compact", 3)
    with pytest.raises(OutOfStock):
        s.checkout("espresso-machine-compact")
    with pytest.raises(OutOfStock):
        s.checkout("reference-open-back-hd")


def test_orders_persist_across_instances(make_store, tmp_path, merchant):
    s1 = store(make_store, tmp_path)
    order = s1.checkout(PRODUCT)
    merchant.confirmed[order["pay_to"]] = PRICE
    s1.status(order["order_id"])
    s2 = Store(
        Catalogue.load(),
        merchant,
        data_dir=tmp_path / "marketplace",
        clock=lambda: date(2026, 10, 12),
    )
    assert s2.status(order["order_id"])["status"] == "paid"
    data = json.loads((tmp_path / "marketplace" / "orders.json").read_text())
    assert len(data["orders"]) == 1


def test_events_emitted(make_store, tmp_path, merchant):
    s = store(make_store, tmp_path)
    s.search(q="scale")
    order = s.checkout(PRODUCT)
    merchant.seen[order["pay_to"]] = PRICE
    s.status(order["order_id"])
    merchant.confirmed[order["pay_to"]] = PRICE
    s.status(order["order_id"])
    events = Path(os.environ["SATCHEL_EVENT_LOG"]).read_text()
    for name in ('"search"', '"order_created"', '"payment_seen"', '"order_paid"'):
        assert name in events
    assert '"marketplace"' in events


def test_search_event_lists_what_was_found(make_store, tmp_path):
    s = store(make_store, tmp_path)
    found = s.search(q="headphones", max_price_usd=200)
    lines = Path(os.environ["SATCHEL_EVENT_LOG"]).read_text().splitlines()
    event = [json.loads(l) for l in lines if '"search"' in l][-1]
    results = event["payload"]["results"]
    assert [r["id"] for r in results] == [p["id"] for p in found["results"]][:12]
    assert set(results[0]) == {"id", "name", "category", "price_sats", "delivery_date"}


def test_checkout_via_api(make_store, tmp_path):
    client = TestClient(create_app(store(make_store, tmp_path)))
    response = client.post("/checkout", json={"product_id": PRODUCT})
    assert response.status_code == 201
    order = response.json()
    assert client.get(f"/orders/{order['order_id']}").status_code == 200
    assert client.post(
        "/checkout", json={"product_id": "nope"}
    ).status_code == 404
    assert client.post(
        "/checkout",
        json={"product_id": "espresso-machine-compact", "quantity": 99},
    ).status_code == 422
    assert client.get(f"/orders/{'0' * 32}").status_code == 404
    assert client.post(
        "/checkout", json={"product_id": "stand-mixer-5l", "quantity": 4}
    ).status_code == 201
    assert client.post(
        "/checkout", json={"product_id": "stand-mixer-5l"}
    ).status_code == 409
