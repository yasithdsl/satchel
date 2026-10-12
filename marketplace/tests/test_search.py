"""Product search through the HTTP API with an injected clock."""

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from satchel_marketplace.app import create_app

MONDAY = date(2026, 10, 12)


def client_for(store):
    return TestClient(create_app(store))


def search(client, **params):
    response = client.get("/products/search", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def friday_for(today: date) -> date:
    days = (4 - today.weekday()) % 7
    if days == 0:
        days = 7
    return today + timedelta(days=days)


@pytest.mark.parametrize("weekday", range(7))
def test_headphones_under_200_by_friday(make_store, tmp_path, weekday):
    today = MONDAY + timedelta(days=weekday)
    client = client_for(make_store(tmp_path, clock=lambda: today))
    friday = friday_for(today)
    body = search(
        client, q="headphones", max_price_usd=200, deliver_by=friday.isoformat()
    )
    ids = {p["id"] for p in body["results"]}
    assert len(ids) >= 3
    assert "halo-pro-anc-headphones" not in ids
    assert "budget-bass-headphones" not in ids
    assert "reference-open-back-hd" not in ids
    for product in body["results"]:
        assert product["price_usd"] <= 200
        assert product["delivery_date"] <= friday.isoformat()


def test_headphones_monday_exact_set(make_store, tmp_path):
    client = client_for(make_store(tmp_path, clock=lambda: MONDAY))
    body = search(
        client,
        q="headphones",
        max_price_usd=200,
        deliver_by=friday_for(MONDAY).isoformat(),
    )
    assert {p["id"] for p in body["results"]} == {
        "citybuds-lite",
        "pulse-sport-earbuds",
        "studio-monitor-mx3-wired",
        "aurora-anc-wireless-headphones",
        "nimbus-over-ear-bluetooth",
    }
    prices = [p["price_usd"] for p in body["results"]]
    assert prices == sorted(prices)


def test_text_tokens_must_all_match(make_store, tmp_path):
    client = client_for(make_store(tmp_path))
    body = search(client, q="wireless headphones")
    ids = {p["id"] for p in body["results"]}
    assert "aurora-anc-wireless-headphones" in ids
    assert "pulse-sport-earbuds" in ids
    assert "studio-monitor-mx3-wired" not in ids
    assert search(client, q="AURORA anc")["count"] == 1
    assert search(client, q="headphones toaster")["count"] == 0


def test_category_filter(make_store, tmp_path):
    client = client_for(make_store(tmp_path))
    body = search(client, category="laptops")
    assert body["count"] == 5
    assert all(p["category"] == "laptops" for p in body["results"])
    assert search(client, category="Kitchen")["count"] == 6


def test_price_filters_are_inclusive(make_store, tmp_path):
    client = client_for(make_store(tmp_path))
    body = search(client, max_price_usd=39)
    assert {p["id"] for p in body["results"]} == {
        "budget-bass-headphones",
        "cast-iron-skillet-26cm",
        "digital-kitchen-scale",
        "usb-c-charger-65w",
    }
    body = search(client, max_price_sats=25_000)
    assert {p["id"] for p in body["results"]} == {"digital-kitchen-scale"}


def test_deliver_by_filter(make_store, tmp_path):
    client = client_for(make_store(tmp_path, clock=lambda: MONDAY))
    body = search(client, deliver_by=MONDAY.isoformat())
    assert {p["id"] for p in body["results"]} == {"citybuds-lite"}
    body = search(
        client, deliver_by=(MONDAY + timedelta(days=1)).isoformat()
    )
    assert all(
        p["delivery_days"] <= 1 for p in body["results"]
    )


def test_out_of_stock_toggle(make_store, tmp_path):
    client = client_for(make_store(tmp_path))
    assert "reference-open-back-hd" not in {
        p["id"] for p in search(client, q="reference")["results"]
    }
    body = search(client, q="reference", include_out_of_stock=True)
    assert [p["id"] for p in body["results"]] == ["reference-open-back-hd"]
    assert body["results"][0]["available"] == 0


def test_sort_by_price_then_delivery(make_store, tmp_path):
    client = client_for(make_store(tmp_path))
    body = search(client)
    keys = [
        (p["price_sats"], p["delivery_days"]) for p in body["results"]
    ]
    assert keys == sorted(keys)


def test_response_envelope(make_store, tmp_path):
    client = client_for(make_store(tmp_path, clock=lambda: MONDAY))
    body = search(client)
    assert body["today"] == MONDAY.isoformat()
    assert body["usd_per_btc"] == 100_000
    assert body["count"] == 19
    assert body["count"] == len(body["results"])


def test_invalid_params_422(make_store, tmp_path):
    client = client_for(make_store(tmp_path))
    response = client.get(
        "/products/search", params={"deliver_by": "next friday"}
    )
    assert response.status_code == 422
    response = client.get(
        "/products/search", params={"max_price_usd": "cheap"}
    )
    assert response.status_code == 422


def test_product_detail(make_store, tmp_path):
    client = client_for(make_store(tmp_path, clock=lambda: MONDAY))
    response = client.get("/products/aurora-anc-wireless-headphones")
    assert response.status_code == 200
    product = response.json()
    assert product["price_sats"] == 179_000
    assert product["delivery_date"] == "2026-10-13"
    assert product["available"] == 12
    assert client.get("/products/nope").status_code == 404


def test_health(make_store, tmp_path):
    client = client_for(make_store(tmp_path))
    assert client.get("/health").json() == {"ok": True}


def test_rate(make_store, tmp_path):
    client = client_for(make_store(tmp_path))
    assert client.get("/rate").json() == {"usd_per_btc": 100_000}
