"""HTTP client for the vault's payload API."""

import os

import httpx

from satchel_core.payloads import Payload, from_http

DEFAULT_VAULT_URL = "http://127.0.0.1:8001"


class VaultClient:
    def __init__(self, base_url: str | None = None, http: httpx.Client | None = None):
        self.base_url = (
            base_url or os.environ.get("SATCHEL_VAULT_URL") or DEFAULT_VAULT_URL
        )
        self._http = http or httpx.Client(base_url=self.base_url)

    def fetch_envelopes(self) -> Payload:
        response = self._http.get("/envelopes/export")
        response.raise_for_status()
        return from_http(response.json())
