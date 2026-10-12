"""Catalogue content and validation."""

from datetime import date

import pytest

from satchel_marketplace.catalogue import (
    USD_PER_BTC,
    Catalogue,
    _validate,
)

PRODUCTS = Catalogue.load()


def test_twenty_products_in_three_plus_categories():
    assert len(PRODUCTS.all(date(2026, 1, 1))) == 20
    categories = {p["category"] for p in PRODUCTS.all(date(2026, 1, 1))}
    assert categories >= {"headphones", "laptops", "kitchen"}


def test_field_types_and_computed_fields():
    for product in PRODUCTS.all(date(2026, 3, 2)):
        assert isinstance(product["id"], str) and product["id"]
        for field in ("name", "category", "description", "seller"):
            assert isinstance(product[field], str) and product[field]
        assert product["price_sats"] > 0
        assert product["price_sats"] == round(
            float(product["price_btc"]) * 100_000_000
        )
        assert product["price_usd"] > 0
        assert product["stock"] >= 0
        assert product["delivery_days"] >= 0
        date.fromisoformat(product["delivery_date"])


def test_exact_btc_parsing():
    aurora = PRODUCTS.get("aurora-anc-wireless-headphones")
    assert aurora["price_btc"] == "0.00179"
    assert aurora["price_sats"] == 179_000
    scale = PRODUCTS.get("digital-kitchen-scale")
    assert scale["price_sats"] == 25_000


def test_usd_within_two_percent():
    for product in PRODUCTS.all(date(2026, 1, 1)):
        expected = product["price_sats"] / 1000
        assert abs(product["price_usd"] - expected) <= expected * 0.02


def test_laptop_priced_above_envelope_budget():
    featherbook = PRODUCTS.get("featherbook-13")
    assert 750 <= featherbook["price_usd"] <= 850
    assert featherbook["price_sats"] > 200_000


def test_usd_per_btc_constant():
    assert USD_PER_BTC == 100_000


def test_delivery_date_from_today():
    for product in PRODUCTS.all(date(2026, 10, 12)):
        delta = (
            date.fromisoformat(product["delivery_date"]) - date(2026, 10, 12)
        ).days
        assert delta == product["delivery_days"]


def _base(**overrides):
    product = {
        "id": "test-product",
        "name": "Test Product",
        "category": "test",
        "description": "A test product.",
        "seller": "Tester",
        "price_btc": "0.001",
        "price_usd": 100,
        "stock": 3,
        "delivery_days": 2,
    }
    product.update(overrides)
    return product


def test_validation_rejects_bad_entries():
    with pytest.raises(ValueError):
        Catalogue([_base(), _base()])
    for bad in (
        _base(id="not a slug"),
        _base(price_btc="0.000000001"),
        _base(price_btc="abc"),
        _base(price_btc="0"),
        _base(price_usd=500),
        _base(price_usd=True),
        _base(stock=-1),
        _base(delivery_days=-1),
        _base(name=123),
    ):
        with pytest.raises(ValueError):
            _validate(bad)
    missing = _base()
    del missing["seller"]
    with pytest.raises(ValueError):
        _validate(missing)
