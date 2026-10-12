"""HTTP client for the air-gapped signer service."""

import os

import httpx

from satchel_core.payloads import Payload, from_http, to_http

DEFAULT_SIGNER_URL = "http://127.0.0.1:8002"


class SignerError(Exception):
    pass


class SignerClient:
    def __init__(
        self, base_url: str | None = None, http: httpx.Client | None = None
    ):
        self.base_url = (
            base_url
            or os.environ.get("SATCHEL_SIGNER_URL")
            or DEFAULT_SIGNER_URL
        )
        self._http = http or httpx.Client(base_url=self.base_url)

    def request_signature(
        self, psbt_payload: Payload, key_release: Payload
    ) -> Payload:
        try:
            response = self._http.post(
                "/sign",
                json={
                    "psbt": to_http(psbt_payload),
                    "keys": to_http(key_release),
                },
            )
            if response.status_code != 200:
                detail = (
                    response.json().get("detail", "") if response.content else ""
                )
                raise SignerError(
                    f"signer returned {response.status_code}: {detail}"
                )
            return from_http(response.json())
        finally:
            keys = key_release.body.get("keys")
            if isinstance(keys, list):
                keys.clear()
