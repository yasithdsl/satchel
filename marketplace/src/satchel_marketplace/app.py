"""HTTP surface of the demo marketplace."""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from satchel_core.regtest import RegtestNode

from .catalogue import USD_PER_BTC, Catalogue
from .merchant import MerchantWallet
from .store import OutOfStock, Store, UnknownOrder, UnknownProduct


class CheckoutRequest(BaseModel):
    product_id: str
    quantity: int = 1


def create_app(store: Store) -> FastAPI:
    app = FastAPI(title="satchel-marketplace")

    @app.get("/health")
    def health():
        return {"ok": True}

    @app.get("/rate")
    def rate():
        return {"usd_per_btc": USD_PER_BTC}

    @app.get("/products/search")
    def search(
        q: str = "",
        category: str | None = None,
        max_price_usd: float | None = None,
        max_price_sats: int | None = None,
        deliver_by: str | None = None,
        include_out_of_stock: bool = False,
    ):
        try:
            return store.search(
                q=q,
                category=category,
                max_price_usd=max_price_usd,
                max_price_sats=max_price_sats,
                deliver_by=deliver_by,
                include_out_of_stock=include_out_of_stock,
            )
        except ValueError as exc:
            raise HTTPException(422, str(exc))

    @app.get("/products/{product_id}")
    def product(product_id: str):
        view = store.product(product_id)
        if view is None:
            raise HTTPException(404, f"unknown product: {product_id}")
        return view

    @app.post("/checkout", status_code=201)
    def checkout(request: CheckoutRequest):
        try:
            return store.checkout(request.product_id, request.quantity)
        except UnknownProduct:
            raise HTTPException(404, f"unknown product: {request.product_id}")
        except OutOfStock as exc:
            raise HTTPException(409, str(exc))
        except ValueError as exc:
            raise HTTPException(422, str(exc))

    @app.get("/orders/{order_id}")
    def order(order_id: str):
        try:
            return store.status(order_id)
        except UnknownOrder:
            raise HTTPException(404, f"unknown order: {order_id}")

    return app


def create_app_from_env() -> FastAPI:
    node = RegtestNode.from_env()
    merchant = MerchantWallet(node)
    merchant.ensure()
    store = Store(Catalogue.load(), merchant)
    return create_app(store)
