"""Product catalogue: loaded from bundled JSON and validated at import."""

import json
import re
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from satchel_core.regtest import btc_to_sats

USD_PER_BTC = 100_000
CATALOGUE_PATH = Path(__file__).with_name("catalogue.json")
SLUG_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
PRICE_BTC_RE = re.compile(r"^[0-9]+(\.[0-9]{1,8})?$")

REQUIRED = {
    "id": str,
    "name": str,
    "category": str,
    "description": str,
    "seller": str,
    "price_btc": str,
    "price_usd": int,
    "stock": int,
    "delivery_days": int,
}
MAX_USD_DEVIATION = 0.02


def _check_int(value, field: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field} must be an integer, got {value!r}")


def _validate(product: dict) -> dict:
    for field, kind in REQUIRED.items():
        if field not in product:
            raise ValueError(f"product missing field {field!r}: {product!r}")
        value = product[field]
        if kind is int:
            _check_int(value, field)
        elif not isinstance(value, kind):
            raise ValueError(f"field {field!r} must be {kind.__name__}")
    if not SLUG_RE.fullmatch(product["id"]):
        raise ValueError(f"invalid product id: {product['id']!r}")
    if not PRICE_BTC_RE.fullmatch(product["price_btc"]):
        raise ValueError(
            f"price_btc must be a decimal string with at most 8 places: "
            f"{product['price_btc']!r}"
        )
    try:
        price_sats = btc_to_sats(Decimal(product["price_btc"]))
    except Exception as exc:
        raise ValueError(
            f"price_btc is not a whole number of satoshis: "
            f"{product['price_btc']!r}"
        ) from exc
    if price_sats <= 0:
        raise ValueError(f"price_btc must be positive: {product!r}")
    expected_usd = price_sats / 1000
    if abs(product["price_usd"] - expected_usd) > expected_usd * MAX_USD_DEVIATION:
        raise ValueError(
            f"price_usd {product['price_usd']} is more than 2% off "
            f"{expected_usd} for product {product['id']!r}"
        )
    if product["stock"] < 0:
        raise ValueError(f"stock must be non-negative: {product['id']!r}")
    if product["delivery_days"] < 0:
        raise ValueError(f"delivery_days must be non-negative: {product['id']!r}")
    result = dict(product)
    result["price_sats"] = price_sats
    return result


class Catalogue:
    def __init__(self, products: list[dict]):
        ids = [p["id"] for p in products]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate product ids in catalogue")
        self._products = {p["id"]: p for p in products}

    @classmethod
    def load(cls, path: str | Path | None = None) -> "Catalogue":
        source = Path(path) if path else CATALOGUE_PATH
        data = json.loads(source.read_text())
        products = data.get("products")
        if not isinstance(products, list) or not products:
            raise ValueError(f"{source} has no 'products' list")
        return cls([_validate(p) for p in products])

    def get(self, product_id: str) -> dict | None:
        product = self._products.get(product_id)
        return dict(product) if product else None

    def all(self, today: date) -> list[dict]:
        return [
            {
                **p,
                "delivery_date": (today + timedelta(days=p["delivery_days"])).isoformat(),
            }
            for p in self._products.values()
        ]
