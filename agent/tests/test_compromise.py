"""Offline tests for the simulated-compromise demo control."""

import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from satchel_agent.clients import LaptopError
from satchel_agent.compromise import LossSink, simulate_compromise
from satchel_agent.server import create_app

from .test_agent import ScriptedClient, make_message
from .test_server import build, parse_sse

from anthropic.types import TextBlock


class StubWallet:
    def __init__(self, balance=200_000, payable=199_500, pending=0):
        self._balance = balance
        self._payable = payable
        self._pending = pending
        self.payments = []

    def balance_sats(self):
        return self._balance

    def pending_change_sats(self):
        return self._pending

    def max_payable_sats(self, address):
        return self._payable

    def pay(self, address, amount_sats):
        self.payments.append((address, amount_sats))
        return "d" * 64


class StubLaptop:
    def __init__(self, response=None, error=None):
        self.response = response or {
            "broadcast": False,
            "txid": None,
            "stage": "approval",
            "reason": "rejected on the Ledger",
        }
        self.error = error
        self.calls = []

    def spend(self, destination, amount_sats, purpose, demo_auto=None):
        self.calls.append(
            {
                "destination": destination,
                "amount_sats": amount_sats,
                "purpose": purpose,
                "demo_auto": demo_auto,
            }
        )
        if self.error is not None:
            raise self.error
        return self.response


class StubSink:
    def __init__(self):
        self.last_address = None
        self.addresses = 0

    def new_address(self):
        self.addresses += 1
        self.last_address = f"bcrt1sink{self.addresses}"
        return self.last_address

    def balance(self):
        return {
            "wallet": "loss-sink",
            "confirmed_sats": 123,
            "pending_sats": 0,
        }


def make_toolbox(wallet=None):
    return SimpleNamespace(
        session_id="sess", agent_id="shopper-dead", wallet=wallet
    )


def event_types():
    path = Path(os.environ["SATCHEL_EVENT_LOG"])
    if not path.exists():
        return []
    return [json.loads(l)["type"] for l in path.read_text().splitlines()]


def event_payload(event_type):
    path = Path(os.environ["SATCHEL_EVENT_LOG"])
    for line in path.read_text().splitlines():
        record = json.loads(line)
        if record["type"] == event_type:
            return record["payload"]
    raise AssertionError(f"no {event_type} event")


def test_drain_runs_before_large_spend_request():
    wallet = StubWallet()
    laptop = StubLaptop()
    order = []
    original_pay = wallet.pay
    original_spend = laptop.spend
    wallet.pay = lambda a, s: (order.append("pay"), original_pay(a, s))[1]
    laptop.spend = lambda *a, **k: (
        order.append("spend"),
        original_spend(*a, **k),
    )[1]
    report = simulate_compromise(
        make_toolbox(wallet), laptop, StubSink()
    )
    assert order == ["pay", "spend"]
    assert report["drained_sats"] == 199_500
    assert wallet.payments == [("bcrt1sink1", 199_500)]
    assert report["envelope_balance_before"] == 200_000
    assert report["large_spend"]["broadcast"] is False
    assert report["large_spend"]["stage"] == "approval"
    assert report["sink"]["wallet"] == "loss-sink"
    assert event_types() == [
        "compromise_started",
        "compromise_envelope_drained",
        "compromise_large_spend_requested",
        "compromise_large_spend_blocked",
        "compromise_finished",
    ]
    drained = event_payload("compromise_envelope_drained")
    assert drained["amount_sats"] == 199_500
    assert drained["txid"] == "d" * 64


def test_no_wallet_still_requests_large_spend():
    laptop = StubLaptop()
    report = simulate_compromise(
        make_toolbox(None), laptop, StubSink()
    )
    assert report["drained_sats"] == 0
    assert report["drain_txid"] is None
    assert len(laptop.calls) == 1
    assert laptop.calls[0]["amount_sats"] == 5_000_000
    assert laptop.calls[0]["purpose"] == "agent top-up"
    types = event_types()
    assert "compromise_envelope_empty" in types
    assert types.index("compromise_envelope_empty") < types.index(
        "compromise_large_spend_requested"
    )


def test_laptop_error_counts_as_blocked():
    laptop = StubLaptop(error=LaptopError("/spends returned 503: approver down"))
    report = simulate_compromise(
        make_toolbox(StubWallet()), laptop, StubSink()
    )
    spend = report["large_spend"]
    assert spend["broadcast"] is False
    assert "503" in spend["reason"]
    types = event_types()
    assert "compromise_large_spend_blocked" in types
    assert "compromise_finished" in types


def test_approved_spend_reports_txid():
    laptop = StubLaptop(
        response={
            "broadcast": True,
            "txid": "a" * 64,
            "stage": "broadcast",
            "reason": None,
        }
    )
    report = simulate_compromise(
        make_toolbox(StubWallet()), laptop, StubSink()
    )
    assert report["large_spend"]["broadcast"] is True
    assert report["large_spend"]["txid"] == "a" * 64
    assert "compromise_large_spend_approved" in event_types()


def test_non_regtest_sink_address_refused():
    class BadSink(StubSink):
        def new_address(self):
            self.last_address = "1mainnetaddress"
            return self.last_address

    with pytest.raises(ValueError):
        simulate_compromise(make_toolbox(StubWallet()), StubLaptop(), BadSink())


def make_app(demo_controls, sink=None, laptop=None):
    agent = build(lambda m: make_message(TextBlock(type="text", text="ok")))
    sessions = {}
    return agent, sessions, TestClient(
        create_app(
            agent,
            sessions,
            demo_controls=demo_controls,
            sink=sink,
            laptop=laptop,
        )
    )


def test_demo_routes_404_when_controls_off():
    _agent, sessions, client = make_app(False, StubSink(), StubLaptop())
    session = _agent.new_session()
    sessions[session.session_id] = session
    response = client.post(
        "/demo/compromise", json={"session_id": session.session_id}
    )
    assert response.status_code == 404
    assert client.get("/demo/loss-sink").status_code == 404


def test_compromise_endpoint_runs_on_session_toolbox():
    agent, sessions, client = make_app(True, StubSink(), StubLaptop())
    session = agent.new_session()
    session.toolbox.wallet = StubWallet()
    sessions[session.session_id] = session
    response = client.post(
        "/demo/compromise",
        json={
            "session_id": session.session_id,
            "request_sats": 5_000_000,
            "demo_auto": "reject",
        },
    )
    assert response.status_code == 200
    report = response.json()
    assert report["drained_sats"] == 199_500
    assert report["large_spend"]["broadcast"] is False
    assert "compromise_finished" in event_types()


def test_compromise_endpoint_unknown_session_404():
    _agent, sessions, client = make_app(True, StubSink(), StubLaptop())
    response = client.post(
        "/demo/compromise", json={"session_id": "missing"}
    )
    assert response.status_code == 404


def test_compromise_endpoint_409_when_busy():
    agent, sessions, client = make_app(True, StubSink(), StubLaptop())
    session = agent.new_session()
    sessions[session.session_id] = session
    session.lock.acquire()
    try:
        response = client.post(
            "/demo/compromise", json={"session_id": session.session_id}
        )
        assert response.status_code == 409
    finally:
        session.lock.release()


def test_loss_sink_endpoint_shape():
    agent, sessions, client = make_app(True, StubSink(), StubLaptop())
    response = client.get("/demo/loss-sink")
    assert response.status_code == 200
    body = response.json()
    assert body == {
        "wallet": "loss-sink",
        "confirmed_sats": 123,
        "pending_sats": 0,
        "last_address": None,
    }
    session = agent.new_session()
    sessions[session.session_id] = session
    client.post(
        "/demo/compromise", json={"session_id": session.session_id}
    )
    assert client.get("/demo/loss-sink").json()["last_address"] == "bcrt1sink1"
