"""State snapshot: aggregate service state over HTTP, per source."""

import os
from datetime import datetime, timezone

import httpx

ENVELOPE_FIELDS = (
    "index",
    "budget_sats",
    "assigned_to",
    "status",
    "balance_sats",
)


def service_urls() -> dict:
    return {
        "laptop": os.environ.get(
            "SATCHEL_LAPTOP_URL", "http://127.0.0.1:8000"
        ),
        "agent": os.environ.get(
            "SATCHEL_AGENT_URL", "http://127.0.0.1:8005"
        ),
        "signer": os.environ.get(
            "SATCHEL_SIGNER_URL", "http://127.0.0.1:8002"
        ),
        "approver": os.environ.get(
            "SATCHEL_APPROVER_URL", "http://127.0.0.1:8003"
        ),
    }


def snapshot(urls: dict | None = None, http=None, timeout: float = 5.0) -> dict:
    urls = urls or service_urls()
    client = http or httpx.Client(timeout=timeout)
    errors = {}

    def fetch(source: str, url: str):
        try:
            response = client.get(url)
            if response.status_code != 200:
                raise RuntimeError(
                    f"GET {url} returned {response.status_code}"
                )
            return response.json()
        except Exception as exc:
            errors[source] = str(exc) or type(exc).__name__
            return None

    main_funds = fetch("main_funds", f"{urls['laptop']}/main-funds")

    envelopes = None
    body = fetch("envelopes", f"{urls['laptop']}/envelopes")
    if body is not None:
        envelopes = [
            {k: e.get(k) for k in ENVELOPE_FIELDS}
            for e in body.get("envelopes", [])
        ]

    loss_sink = None
    try:
        response = client.get(f"{urls['agent']}/demo/loss-sink")
        if response.status_code == 200:
            loss_sink = response.json()
        elif response.status_code != 404:
            raise RuntimeError(
                f"GET /demo/loss-sink returned {response.status_code}"
            )
    except Exception as exc:
        errors["loss_sink"] = str(exc) or type(exc).__name__

    random_nonce = fetch(
        "random_nonce_signer", f"{urls['signer']}/demo/random-nonce"
    )
    if random_nonce is not None:
        random_nonce = random_nonce.get("enabled")

    compromise_control = None
    health = fetch("compromise_control", f"{urls['agent']}/health")
    if health is not None:
        compromise_control = {
            "enabled": bool(health.get("demo_controls"))
        }

    pending = fetch("pending_approval", f"{urls['approver']}/pending")

    return {
        "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        "main_funds": main_funds,
        "envelopes": envelopes,
        "loss_sink": loss_sink,
        "random_nonce_signer": random_nonce,
        "compromise_control": compromise_control,
        "pending_approval": pending,
        "errors": errors,
    }
