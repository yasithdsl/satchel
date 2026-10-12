"""HTTP client for the vault's payload API."""

import os

import httpx

from satchel_core.payloads import Payload, from_http, to_http

DEFAULT_VAULT_URL = "http://127.0.0.1:8001"


class VaultRefused(Exception):
    """The vault refused a request (403/409); carries status and detail."""

    def __init__(self, status: int, reason: str):
        super().__init__(f"vault refused ({status}): {reason}")
        self.status = status
        self.reason = reason


class VaultClient:
    def __init__(self, base_url: str | None = None, http: httpx.Client | None = None):
        self.base_url = (
            base_url or os.environ.get("SATCHEL_VAULT_URL") or DEFAULT_VAULT_URL
        )
        self._http = http or httpx.Client(base_url=self.base_url)

    def _check(self, response: httpx.Response) -> None:
        if response.status_code in (403, 409):
            raise VaultRefused(
                response.status_code, response.json().get("detail", "")
            )
        response.raise_for_status()

    def fetch_envelopes(self) -> Payload:
        response = self._http.get("/envelopes/export")
        self._check(response)
        return from_http(response.json())

    def export_receive(self, count: int) -> Payload:
        response = self._http.post(
            "/addresses/export", json={"count": count, "kind": "receive"}
        )
        self._check(response)
        return from_http(response.json())

    def export_change(self, count: int) -> Payload:
        response = self._http.post(
            "/addresses/export", json={"count": count, "kind": "change"}
        )
        self._check(response)
        return from_http(response.json())

    def release_envelope(self, approval: Payload) -> Payload:
        response = self._http.post(
            "/release/envelope", json={"approval": to_http(approval)}
        )
        self._check(response)
        return from_http(response.json())

    def release_spend(self, approval: Payload, psbt_payload: Payload) -> Payload:
        response = self._http.post(
            "/release/spend",
            json={"approval": to_http(approval), "psbt": to_http(psbt_payload)},
        )
        self._check(response)
        return from_http(response.json())

    def verify(self, psbt_payload: Payload, signed_payload: Payload) -> Payload:
        response = self._http.post(
            "/verify",
            json={"psbt": to_http(psbt_payload), "signed": to_http(signed_payload)},
        )
        self._check(response)
        return from_http(response.json())
