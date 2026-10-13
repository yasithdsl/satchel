"""X-ray app: SSE backlog/live/resume, state endpoint, proxies, CORS."""

import json
import threading
import time
from contextlib import contextmanager

import httpx
import pytest
import uvicorn
from fastapi.testclient import TestClient

from satchel_xray.app import create_app
from satchel_xray.enrich import Enricher
from satchel_xray.tail import EventTailer


def event(ts, etype="thing", component="laptop", payload=None):
    return {
        "id": f"id-{ts}-{etype}",
        "ts": ts,
        "component": component,
        "type": etype,
        "message": f"msg {etype}",
        "payload": payload,
    }


def write_log(path, events):
    path.write_text("".join(json.dumps(e) + "\n" for e in events))


def build(tmp_path, events=(), **kwargs):
    log = tmp_path / "events.jsonl"
    write_log(log, events)
    kwargs.setdefault("poll_interval", 0.02)
    kwargs.setdefault("keepalive", 0.5)
    app = create_app(EventTailer([log]), Enricher(), **kwargs)
    return app, log


@contextmanager
def serve(app):
    config = uvicorn.Config(
        app, host="127.0.0.1", port=0, log_level="warning"
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        for _ in range(500):
            if server.started:
                break
            time.sleep(0.02)
        else:
            raise RuntimeError("uvicorn did not start")
        port = server.servers[0].sockets[0].getsockname()[1]
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=10)


def take(lines, count, timeout=20.0):
    events = []
    deadline = time.time() + timeout
    for line in lines:
        if line.startswith("data: "):
            events.append(json.loads(line[6:]))
            if len(events) >= count:
                return events
        if time.time() > deadline:
            break
    return events


def test_health(tmp_path):
    app, _ = build(tmp_path)
    body = TestClient(app).get("/health").json()
    assert body["ok"] is True
    assert isinstance(body["boot_id"], str) and body["boot_id"]


def test_boot_id_unique(tmp_path):
    app_one, _ = build(tmp_path)
    app_two, _ = build(tmp_path)
    one = TestClient(app_one).get("/health").json()["boot_id"]
    two = TestClient(app_two).get("/health").json()["boot_id"]
    assert one != two


def test_events_carry_boot_id(tmp_path):
    app, _ = build(
        tmp_path, [event("2026-10-12T20:00:00.000+00:00")]
    )
    app.state.pump()
    event_out = app.state.ring[-1]
    health = TestClient(app).get("/health").json()
    assert event_out["boot"] == health["boot_id"]


def test_sse_backlog(tmp_path):
    app, _ = build(
        tmp_path,
        [event(f"2026-10-12T20:00:0{i}.000+00:00") for i in range(3)],
    )
    with serve(app) as base:
        time.sleep(0.2)
        with httpx.stream("GET", f"{base}/events?backlog=2") as r:
            assert r.status_code == 200
            found = take(r.iter_lines(), 2)
    assert [e["seq"] for e in found] == [2, 3]


def test_sse_backlog_default_limit(tmp_path):
    app, _ = build(
        tmp_path,
        [event(f"2026-10-12T20:00:0{i}.000+00:00") for i in range(3)],
    )
    with serve(app) as base:
        time.sleep(0.2)
        with httpx.stream("GET", f"{base}/events") as r:
            found = take(r.iter_lines(), 3)
    assert [e["seq"] for e in found] == [1, 2, 3]


def test_sse_live_delivery(tmp_path):
    app, log = build(tmp_path, [event("2026-10-12T20:00:00.000+00:00")])
    with serve(app) as base:
        time.sleep(0.2)
        with httpx.stream("GET", f"{base}/events?backlog=0") as r:
            time.sleep(0.2)
            with log.open("a") as handle:
                handle.write(
                    json.dumps(
                        event(
                            "2026-10-12T20:01:00.000+00:00",
                            "live_thing",
                        )
                    )
                    + "\n"
                )
            found = take(r.iter_lines(), 1)
    assert len(found) == 1
    assert found[0]["type"] == "live_thing"
    assert found[0]["seq"] == 2


def test_sse_resume_with_last_event_id(tmp_path):
    app, _ = build(
        tmp_path,
        [event(f"2026-10-12T20:00:0{i}.000+00:00") for i in range(4)],
    )
    with serve(app) as base:
        time.sleep(0.2)
        with httpx.stream(
            "GET", f"{base}/events", headers={"Last-Event-ID": "2"}
        ) as r:
            found = take(r.iter_lines(), 2)
    assert [e["seq"] for e in found] == [3, 4]


def test_enriched_fields_on_stream(tmp_path):
    app, _ = build(
        tmp_path,
        [
            event(
                "2026-10-12T20:00:00.000+00:00",
                "plan_sent_to_approver",
                payload={
                    "flow_id": "f1",
                    "flow": "spend",
                    "hop": 0,
                    "from": "laptop",
                    "to": "approver",
                },
            )
        ],
    )
    with serve(app) as base:
        time.sleep(0.2)
        with httpx.stream("GET", f"{base}/events?backlog=1") as r:
            found = take(r.iter_lines(), 1)
    out = found[0]
    assert out["nodes"] == {"from": "laptop", "to": "ledger"}
    assert out["label"] == "Laptop → Ledger: plan for the human to approve"


def test_cors_headers(tmp_path):
    app, _ = build(tmp_path)
    client = TestClient(app)
    response = client.get(
        "/health", headers={"Origin": "http://localhost:3000"}
    )
    assert (
        response.headers["access-control-allow-origin"]
        == "http://localhost:3000"
    )
    preflight = client.options(
        "/events",
        headers={
            "Origin": "http://127.0.0.1:3000",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert (
        preflight.headers["access-control-allow-origin"]
        == "http://127.0.0.1:3000"
    )
    web3100 = client.get(
        "/health", headers={"Origin": "http://localhost:3100"}
    )
    assert (
        web3100.headers["access-control-allow-origin"]
        == "http://localhost:3100"
    )


class Resp:
    def __init__(self, status_code, body):
        self.status_code = status_code
        self._body = body

    def json(self):
        return self._body


class StubHttp:
    def __init__(self):
        self.posts = []
        self.gets = []

    def get(self, url):
        self.gets.append(url)
        raise RuntimeError("no stub route")

    def post(self, url, json=None):
        self.posts.append((url, json))
        return Resp(200, {"enabled": json["enabled"]})


def test_random_nonce_proxy(tmp_path):
    http = StubHttp()
    urls = {
        "laptop": "http://l",
        "agent": "http://a",
        "signer": "http://signer",
        "approver": "http://p",
    }
    app, _ = build(tmp_path, urls=urls, http=http)
    response = TestClient(app).post(
        "/demo/random-nonce", json={"enabled": True}
    )
    assert response.status_code == 200
    assert response.json() == {"enabled": True}
    assert http.posts == [
        ("http://signer/demo/random-nonce", {"enabled": True})
    ]


def test_state_endpoint(tmp_path):
    app, _ = build(tmp_path, http=StubHttp())
    body = TestClient(app).get("/state").json()
    assert set(body) == {
        "ts",
        "main_funds",
        "envelopes",
        "loss_sink",
        "random_nonce_signer",
        "compromise_control",
        "pending_approval",
        "errors",
    }
    assert body["errors"]


@pytest.mark.regtest
def test_mine_endpoint(node, tmp_path):
    app, _ = build(tmp_path, node=node)
    response = TestClient(app).post("/demo/mine")
    assert response.status_code == 200
    block_hash = response.json()["block_hash"]
    assert isinstance(block_hash, str) and len(block_hash) == 64


def test_mine_without_node_503(tmp_path):
    app, _ = build(tmp_path)
    assert TestClient(app).post("/demo/mine").status_code == 503


class FakeNode:
    def faucet_address(self):
        return "bcrt1qfaucet"

    def mine_blocks(self, count, address):
        assert count == 1
        return ["ab" * 32]


def test_mine_emits_block_mined(tmp_path, monkeypatch):
    app, log = build(tmp_path, node=FakeNode())
    monkeypatch.setenv("SATCHEL_EVENT_LOG", str(log))
    response = TestClient(app).post("/demo/mine")
    assert response.status_code == 200
    app.state.pump()
    found = [
        e for e in app.state.ring if e["type"] == "block_mined"
    ]
    assert len(found) == 1
    assert found[0]["component"] == "network"
    assert found[0]["payload"]["block_hash"] == "ab" * 32
    assert "nodes" not in found[0]


class LedgerHttp(StubHttp):
    def __init__(self):
        super().__init__()
        self.gets = []
        self.routes = {}
        self.screenshot_body = b"png-bytes"

    def get(self, url):
        self.gets.append(url)
        for prefix, value in self.routes.items():
            if url.startswith(prefix):
                status, body = value
                return Resp(status, body)
        if url.endswith("/screenshot"):
            resp = Resp(200, {})
            resp.content = self.screenshot_body
            return resp
        raise RuntimeError(f"no stub route for {url}")

    def post(self, url, json=None, timeout=None):
        self.posts.append((url, json))
        for prefix, value in self.routes.items():
            if url.startswith(prefix):
                status, body = value
                return Resp(status, body)
        return Resp(200, {})


def ledger_app(tmp_path, http):
    urls = {
        "laptop": "http://l",
        "agent": "http://a",
        "signer": "http://s",
        "approver": "http://approver",
    }
    app, _ = build(
        tmp_path,
        urls=urls,
        http=http,
        speculos_url="http://speculos",
    )
    return app


def test_ledger_screenshot_proxy(tmp_path):
    http = LedgerHttp()
    app = ledger_app(tmp_path, http)
    response = TestClient(app).get("/ledger/screenshot")
    assert response.status_code == 200
    assert response.content == b"png-bytes"
    assert response.headers["cache-control"] == "no-store"
    assert "http://speculos/screenshot" in http.gets


def test_ledger_screen_text(tmp_path):
    http = LedgerHttp()
    http.routes["http://speculos/events"] = (
        200,
        {"events": [{"text": "Review message"}, {"text": "Pay 0.05"}]},
    )
    app = ledger_app(tmp_path, http)
    body = TestClient(app).get("/ledger/screen-text").json()
    assert body == {"texts": ["Review message", "Pay 0.05"]}


def test_ledger_finger_proxy_and_validation(tmp_path):
    http = LedgerHttp()
    app = ledger_app(tmp_path, http)
    client = TestClient(app)
    ok = client.post(
        "/ledger/finger",
        json={
            "action": "press-and-release",
            "x": 400,
            "y": 300,
            "x2": 80,
            "y2": 300,
            "delay": 0.4,
        },
    )
    assert ok.status_code == 200
    assert http.posts[-1] == (
        "http://speculos/finger",
        {
            "action": "press-and-release",
            "x": 400,
            "y": 300,
            "x2": 80,
            "y2": 300,
            "delay": 0.4,
        },
    )
    frac = client.post(
        "/ledger/finger",
        json={"action": "press", "x": 400.6, "y": 299.4},
    )
    assert frac.status_code == 200
    assert http.posts[-1] == (
        "http://speculos/finger",
        {"action": "press", "x": 401, "y": 299},
    )
    assert (
        client.post(
            "/ledger/finger", json={"action": "poke", "x": 1, "y": 1}
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/ledger/finger",
            json={"action": "press", "x": 480, "y": 1},
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/ledger/finger",
            json={"action": "press", "x": 1, "y": 600},
        ).status_code
        == 422
    )


def test_ledger_approve_reject_proxy(tmp_path):
    http = LedgerHttp()
    app = ledger_app(tmp_path, http)
    client = TestClient(app)
    assert client.post("/ledger/approve").status_code == 200
    assert client.post("/ledger/reject").status_code == 200
    assert http.posts == [
        ("http://approver/demo/approve", {}),
        ("http://approver/demo/reject", {}),
    ]


def test_ledger_action_automation_off(tmp_path):
    http = LedgerHttp()
    http.routes["http://approver/demo/approve"] = (404, {})
    app = ledger_app(tmp_path, http)
    response = TestClient(app).post("/ledger/approve")
    assert response.status_code == 409
    assert "automation" in response.json()["detail"]


def test_ledger_automation_flag(tmp_path):
    http = LedgerHttp()
    http.routes["http://approver/health"] = (
        200,
        {"ok": True, "demo_automation": True},
    )
    app = ledger_app(tmp_path, http)
    body = TestClient(app).get("/ledger/automation").json()
    assert body == {"automation": True}
