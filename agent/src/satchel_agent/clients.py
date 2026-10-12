"""HTTP clients for the marketplace and the laptop coordinator."""

import os

import httpx

DEFAULT_MARKETPLACE_URL = "http://127.0.0.1:8004"
DEFAULT_LAPTOP_URL = "http://127.0.0.1:8000"


class MarketplaceError(Exception):
    pass


class LaptopError(Exception):
    pass


def _detail(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return response.text[:200]
    detail = body.get("detail")
    return detail if isinstance(detail, str) else str(body)[:200]


class MarketplaceClient:
    def __init__(
        self, base_url: str | None = None, http: httpx.Client | None = None
    ):
        self.base_url = (
            base_url
            or os.environ.get("SATCHEL_MARKETPLACE_URL")
            or DEFAULT_MARKETPLACE_URL
        )
        self._http = http or httpx.Client(base_url=self.base_url)

    def _get(self, path: str, params: dict | None = None) -> dict:
        response = self._http.get(path, params=params)
        if response.status_code != 200:
            raise MarketplaceError(
                f"marketplace {path} returned {response.status_code}: "
                f"{_detail(response)}"
            )
        return response.json()

    def search(
        self,
        query: str,
        max_price_usd=None,
        deliver_by=None,
        category=None,
    ) -> dict:
        params = {"q": query}
        if max_price_usd is not None:
            params["max_price_usd"] = max_price_usd
        if deliver_by is not None:
            params["deliver_by"] = deliver_by
        if category is not None:
            params["category"] = category
        return self._get("/products/search", params)

    def product(self, product_id: str) -> dict:
        return self._get(f"/products/{product_id}")

    def checkout(self, product_id: str, quantity: int = 1) -> dict:
        response = self._http.post(
            "/checkout",
            json={"product_id": product_id, "quantity": quantity},
        )
        if response.status_code not in (200, 201):
            raise MarketplaceError(
                f"checkout returned {response.status_code}: "
                f"{_detail(response)}"
            )
        return response.json()

    def order(self, order_id: str) -> dict:
        return self._get(f"/orders/{order_id}")

    def rate(self) -> dict:
        return self._get("/rate")


class LaptopClient:
    def __init__(
        self,
        base_url: str | None = None,
        http: httpx.Client | None = None,
        timeout: float = 300,
    ):
        self.base_url = (
            base_url
            or os.environ.get("SATCHEL_LAPTOP_URL")
            or DEFAULT_LAPTOP_URL
        )
        self._http = http or httpx.Client(
            base_url=self.base_url, timeout=timeout
        )
        self._timeout = timeout

    def grant(
        self, agent_id: str, budget_sats: int, demo_auto: str | None = None
    ) -> dict:
        body = {"agent_id": agent_id, "budget_sats": budget_sats}
        if demo_auto is not None:
            body["demo_auto"] = demo_auto
        response = self._http.post("/grants", json=body, timeout=self._timeout)
        if response.status_code != 200:
            raise LaptopError(
                f"/grants returned {response.status_code}: {_detail(response)}"
            )
        return response.json()

    def spend(
        self,
        destination: str,
        amount_sats: int,
        purpose: str,
        demo_auto: str | None = None,
    ) -> dict:
        body = {
            "destination": destination,
            "amount_sats": amount_sats,
            "purpose": purpose,
        }
        if demo_auto is not None:
            body["demo_auto"] = demo_auto
        response = self._http.post("/spends", json=body, timeout=self._timeout)
        if response.status_code != 200:
            raise LaptopError(
                f"/spends returned {response.status_code}: {_detail(response)}"
            )
        return response.json()
