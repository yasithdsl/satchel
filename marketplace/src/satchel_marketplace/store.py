"""Order store: checkout, stock accounting and payment status."""

import json
import os
import tempfile
import threading
import uuid
from datetime import date, datetime, timezone
from pathlib import Path

from satchel_core.events import emit
from satchel_core.regtest import sats_to_btc

from .catalogue import Catalogue, USD_PER_BTC

MAX_QUANTITY = 10


SEARCH_EVENT_RESULTS = 12


class UnknownProduct(KeyError):
    pass


class UnknownOrder(KeyError):
    pass


class OutOfStock(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class Store:
    def __init__(
        self,
        catalogue: Catalogue,
        merchant,
        data_dir: str | Path | None = None,
        clock=None,
    ):
        self.catalogue = catalogue
        self.merchant = merchant
        self.data_dir = Path(
            data_dir
            or os.environ.get("SATCHEL_MARKETPLACE_DIR", ".satchel/marketplace")
        )
        self._orders_path = self.data_dir / "orders.json"
        self._clock = clock or date.today
        self._lock = threading.Lock()
        self._orders: dict[str, dict] = self._load()

    def _load(self) -> dict[str, dict]:
        if not self._orders_path.exists():
            return {}
        data = json.loads(self._orders_path.read_text())
        return {o["order_id"]: o for o in data.get("orders", [])}

    def _save(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(
            dir=self.data_dir, prefix=".orders-", suffix=".json"
        )
        try:
            with os.fdopen(fd, "w") as handle:
                json.dump(
                    {"orders": list(self._orders.values())},
                    handle,
                    indent=1,
                )
            os.replace(tmp, self._orders_path)
        except BaseException:
            os.unlink(tmp)
            raise

    def today(self) -> date:
        return self._clock()

    def _reserved(self, product_id: str) -> int:
        return sum(
            o["quantity"]
            for o in self._orders.values()
            if o["product_id"] == product_id
        )

    def product(self, product_id: str) -> dict | None:
        product = self.catalogue.get(product_id)
        if product is None:
            return None
        view = dict(product)
        view["delivery_date"] = (
            date.fromordinal(
                self.today().toordinal() + product["delivery_days"]
            ).isoformat()
        )
        view["available"] = product["stock"] - self._reserved(product_id)
        return view

    def search(
        self,
        q: str = "",
        category: str | None = None,
        max_price_usd: float | None = None,
        max_price_sats: int | None = None,
        deliver_by: str | None = None,
        include_out_of_stock: bool = False,
    ) -> dict:
        today = self.today()
        deadline = None
        if deliver_by is not None:
            try:
                deadline = date.fromisoformat(deliver_by)
            except ValueError as exc:
                raise ValueError(
                    f"deliver_by must be a YYYY-MM-DD date: {deliver_by!r}"
                ) from exc
        tokens = [t.lower() for t in q.split() if t.strip()]
        results = []
        for product in self.catalogue.all(today):
            view = dict(product)
            view["available"] = product["stock"] - self._reserved(product["id"])
            haystack = " ".join(
                [
                    product["name"],
                    product["category"],
                    product["description"],
                    product["seller"],
                ]
            ).lower()
            if any(token not in haystack for token in tokens):
                continue
            if (
                category is not None
                and product["category"].lower() != category.lower()
            ):
                continue
            if (
                max_price_usd is not None
                and product["price_usd"] > max_price_usd
            ):
                continue
            if (
                max_price_sats is not None
                and product["price_sats"] > max_price_sats
            ):
                continue
            if deadline is not None and (
                date.fromisoformat(view["delivery_date"]) > deadline
            ):
                continue
            if view["available"] <= 0 and not include_out_of_stock:
                continue
            results.append(view)
        results.sort(key=lambda p: (p["price_sats"], p["delivery_days"]))
        emit(
            "marketplace",
            "search",
            f"search returned {len(results)} products",
            {
                "q": q,
                "category": category,
                "max_price_usd": max_price_usd,
                "max_price_sats": max_price_sats,
                "deliver_by": deliver_by,
                "include_out_of_stock": include_out_of_stock,
                "count": len(results),
                # Public catalogue data, so the x-ray can show what the
                # agent browsed.
                "results": [
                    {
                        "id": p["id"],
                        "name": p["name"],
                        "category": p["category"],
                        "price_sats": p["price_sats"],
                        "delivery_date": p["delivery_date"],
                    }
                    for p in results[:SEARCH_EVENT_RESULTS]
                ],
            },
        )
        return {
            "today": today.isoformat(),
            "usd_per_btc": USD_PER_BTC,
            "count": len(results),
            "results": results,
        }

    def checkout(self, product_id: str, quantity: int = 1) -> dict:
        if (
            isinstance(quantity, bool)
            or not isinstance(quantity, int)
            or not 1 <= quantity <= MAX_QUANTITY
        ):
            raise ValueError(f"quantity must be an integer 1..{MAX_QUANTITY}")
        with self._lock:
            product = self.catalogue.get(product_id)
            if product is None:
                raise UnknownProduct(product_id)
            available = product["stock"] - self._reserved(product_id)
            if quantity > available:
                raise OutOfStock(
                    f"requested {quantity} but only {available} of "
                    f"{product_id} available"
                )
            order_id = uuid.uuid4().hex
            amount_sats = product["price_sats"] * quantity
            amount_btc = sats_to_btc(amount_sats)
            pay_to = self.merchant.new_address(label=order_id)
            order = {
                "order_id": order_id,
                "product_id": product_id,
                "name": product["name"],
                "quantity": quantity,
                "amount_sats": amount_sats,
                "amount_btc": amount_btc,
                "amount_usd": product["price_usd"] * quantity,
                "pay_to": pay_to,
                "payment_uri": f"bitcoin:{pay_to}?amount={amount_btc}",
                "status": "awaiting_payment",
                "created_at": _now(),
                "delivery_date": date.fromordinal(
                    self.today().toordinal() + product["delivery_days"]
                ).isoformat(),
                "paid_at": None,
                "txids": [],
            }
            self._orders[order_id] = order
            self._save()
        emit(
            "marketplace",
            "order_created",
            f"order {order_id[:8]} for {product_id}",
            {
                "order_id": order_id,
                "product_id": product_id,
                "amount_sats": amount_sats,
                "pay_to": pay_to,
            },
        )
        return dict(order)

    def status(self, order_id: str) -> dict:
        with self._lock:
            return self._status(order_id)

    def _status(self, order_id: str) -> dict:
        order = self._orders.get(order_id)
        if order is None:
            raise UnknownOrder(order_id)
        if order["status"] == "paid":
            return {
                **order,
                "received_sats": order["amount_sats"],
                "pending_sats": 0,
            }
        confirmed = self.merchant.received_sats(order["pay_to"], 1)
        seen = self.merchant.received_sats(order["pay_to"], 0)
        amount = order["amount_sats"]
        if confirmed >= amount:
            order["status"] = "paid"
            order["paid_at"] = _now()
            order["txids"] = self.merchant.txids(order["pay_to"])
            self._save()
            emit(
                "marketplace",
                "order_paid",
                f"order {order_id[:8]} paid {amount} sats",
                {"order_id": order_id, "txids": order["txids"]},
            )
        elif seen >= amount:
            if order["status"] != "payment_pending":
                emit(
                    "marketplace",
                    "payment_seen",
                    f"unconfirmed payment seen for order {order_id[:8]}",
                    {"order_id": order_id, "seen_sats": seen},
                )
            order["status"] = "payment_pending"
            self._save()
        elif 0 < confirmed < amount:
            order["status"] = "underpaid"
            self._save()
        else:
            order["status"] = "awaiting_payment"
            self._save()
        return {**order, "received_sats": confirmed, "pending_sats": seen}
