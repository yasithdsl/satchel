"""HTTP client for the Ledger approver service."""

import os
from dataclasses import dataclass

import httpx

from satchel_core.payloads import Payload, from_http

DEFAULT_APPROVER_URL = "http://127.0.0.1:8003"


class ApproverError(Exception):
    pass


@dataclass
class ApprovalOutcome:
    approved: bool
    payload: Payload | None
    reason: str | None
    nonce: str | None
    text: str | None


class ApproverClient:
    def __init__(
        self,
        base_url: str | None = None,
        http: httpx.Client | None = None,
        timeout: float = 180,
    ):
        self.base_url = (
            base_url
            or os.environ.get("SATCHEL_APPROVER_URL")
            or DEFAULT_APPROVER_URL
        )
        self._http = http or httpx.Client(
            base_url=self.base_url, timeout=timeout
        )
        self._timeout = timeout

    def approve(self, plan: dict, demo_auto: str | None = None) -> ApprovalOutcome:
        body: dict = {"plan": plan}
        if demo_auto is not None:
            body["demo_auto"] = demo_auto
        response = self._http.post("/approve", json=body, timeout=self._timeout)
        if response.status_code == 200:
            return ApprovalOutcome(
                approved=True,
                payload=from_http(response.json()),
                reason=None,
                nonce=None,
                text=None,
            )
        detail = response.json() if response.content else {}
        if response.status_code == 409 and detail.get("status") == "rejected":
            return ApprovalOutcome(
                approved=False,
                payload=None,
                reason=detail.get("reason"),
                nonce=detail.get("nonce"),
                text=detail.get("text"),
            )
        raise ApproverError(
            f"approver returned {response.status_code}: {detail}"
        )

    def address(self) -> dict:
        response = self._http.get("/address")
        response.raise_for_status()
        return response.json()
