"""Laptop HTTP API tests with stub client and node."""

import httpx
from fastapi.testclient import TestClient

from satchel_core.regtest import NodeUnavailable
from satchel_laptop.app import create_app
from satchel_laptop.state import LaptopState

from .test_envelopes import StubNode, export_payload, utxo


class StubVaultClient:
    def __init__(self, payload=None, error=None):
        self._payload = payload
        self._error = error

    def fetch_envelopes(self):
        if self._error is not None:
            raise self._error
        return self._payload


def test_get_envelopes(tmp_path):
    payload = export_payload(count=2)
    address = payload.body["addresses"][0]["address"]
    node = StubNode(utxos=[utxo(address)])
    app = create_app(StubVaultClient(payload), node, LaptopState(tmp_path / "s.json"))
    body = TestClient(app).get("/envelopes").json()
    statuses = {e["index"]: e for e in body["envelopes"]}
    assert statuses[0]["status"] == "unassigned"
    assert statuses[0]["balance_sats"] == 50_000
    assert statuses[1]["status"] == "unfunded"
    assert statuses[1]["budget_sats"] == 50_000


def test_vault_unreachable_returns_502(tmp_path):
    client = StubVaultClient(error=httpx.ConnectError("connection refused"))
    app = create_app(client, StubNode(), LaptopState(tmp_path / "s.json"))
    response = TestClient(app).get("/envelopes")
    assert response.status_code == 502
    assert "vault" in response.json()["detail"]


def test_bad_vault_payload_returns_502(tmp_path):
    client = StubVaultClient(error=ValueError("bad vault payload"))
    app = create_app(client, StubNode(), LaptopState(tmp_path / "s.json"))
    response = TestClient(app).get("/envelopes")
    assert response.status_code == 502


def test_node_unreachable_returns_503(tmp_path):
    class DownNode:
        def list_unspent(self, addresses):
            raise NodeUnavailable("connection refused")

    client = StubVaultClient(export_payload(count=1))
    app = create_app(client, DownNode(), LaptopState(tmp_path / "s.json"))
    response = TestClient(app).get("/envelopes")
    assert response.status_code == 503
    assert "bitcoind" in response.json()["detail"]
