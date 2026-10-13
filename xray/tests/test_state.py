"""State snapshot aggregation over stub HTTP sources."""

import httpx
import pytest

from satchel_xray.state import snapshot

URLS = {
    "laptop": "http://laptop",
    "agent": "http://agent",
    "signer": "http://signer",
    "approver": "http://approver",
}

MAIN_FUNDS = {
    "fingerprint": "abcd1234",
    "addresses": 3,
    "utxos": 3,
    "balance_sats": 100_000_000,
    "available_sats": 90_000_000,
}

ENVELOPES_BODY = {
    "envelopes": [
        {
            "index": 0,
            "address": "bcrt1qenv0",
            "budget_sats": 100_000,
            "assigned_to": "shopper-x",
            "status": "assigned",
            "balance_sats": 80_000,
            "available_sats": 60_000,
            "utxo_count": 1,
        }
    ]
}

LOSS_SINK = {
    "wallet": "loss-sink",
    "confirmed_sats": 12_345,
    "pending_sats": 0,
    "last_address": "bcrt1qsink",
}

PENDING = {
    "pending": {
        "kind": "large_spend",
        "text": "Approve spending...",
        "nonce": "ab" * 8,
        "started_at": "2026-10-12T20:00:00.000Z",
    }
}


class Resp:
    def __init__(self, status_code, body=None):
        self.status_code = status_code
        self._body = body or {}

    def json(self):
        return self._body


class StubHttp:
    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def get(self, url):
        self.calls.append(url)
        result = self.routes.get(url)
        if isinstance(result, Exception):
            raise result
        if result is None:
            raise httpx.ConnectError(f"no route for {url}")
        return result


def full_routes():
    return {
        "http://laptop/main-funds": Resp(200, MAIN_FUNDS),
        "http://laptop/envelopes": Resp(200, ENVELOPES_BODY),
        "http://agent/demo/loss-sink": Resp(200, LOSS_SINK),
        "http://agent/health": Resp(200, {"ok": True, "demo_controls": True}),
        "http://signer/demo/random-nonce": Resp(200, {"enabled": True}),
        "http://approver/pending": Resp(200, PENDING),
    }


def test_snapshot_aggregates_all_sources():
    http = StubHttp(full_routes())
    result = snapshot(URLS, http=http)
    assert result["ts"].endswith("+00:00")
    assert result["main_funds"] == MAIN_FUNDS
    assert result["envelopes"] == [
        {
            "index": 0,
            "budget_sats": 100_000,
            "assigned_to": "shopper-x",
            "status": "assigned",
            "balance_sats": 80_000,
            "available_sats": 60_000,
        }
    ]
    assert result["loss_sink"] == LOSS_SINK
    assert result["random_nonce_signer"] is True
    assert result["compromise_control"] == {"enabled": True}
    assert result["pending_approval"] == PENDING
    assert result["errors"] == {}


def test_failing_source_nulls_only_its_field():
    routes = full_routes()
    routes["http://approver/pending"] = httpx.ConnectError(
        "approver down"
    )
    result = snapshot(URLS, http=StubHttp(routes))
    assert result["pending_approval"] is None
    assert "approver down" in result["errors"]["pending_approval"]
    assert result["main_funds"] == MAIN_FUNDS
    assert result["envelopes"]
    assert result["loss_sink"] == LOSS_SINK
    assert result["compromise_control"] == {"enabled": True}


def test_http_error_status_is_an_error():
    routes = full_routes()
    routes["http://laptop/main-funds"] = Resp(503, {"detail": "down"})
    result = snapshot(URLS, http=StubHttp(routes))
    assert result["main_funds"] is None
    assert "503" in result["errors"]["main_funds"]


def test_loss_sink_404_is_null_without_error():
    routes = full_routes()
    routes["http://agent/demo/loss-sink"] = Resp(404, {"detail": "off"})
    result = snapshot(URLS, http=StubHttp(routes))
    assert result["loss_sink"] is None
    assert "loss_sink" not in result["errors"]
    assert result["compromise_control"] == {"enabled": True}


def test_agent_down_errors_both_agent_fields():
    routes = full_routes()
    routes["http://agent/demo/loss-sink"] = httpx.ConnectError("down")
    routes["http://agent/health"] = httpx.ConnectError("down")
    result = snapshot(URLS, http=StubHttp(routes))
    assert result["loss_sink"] is None
    assert result["compromise_control"] is None
    assert "loss_sink" in result["errors"]
    assert "compromise_control" in result["errors"]
    assert result["main_funds"] == MAIN_FUNDS


def test_demo_controls_off_reports_disabled():
    routes = full_routes()
    routes["http://agent/health"] = Resp(
        200, {"ok": True, "demo_controls": False}
    )
    result = snapshot(URLS, http=StubHttp(routes))
    assert result["compromise_control"] == {"enabled": False}
