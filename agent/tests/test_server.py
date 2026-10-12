"""SSE chat endpoint and session handling."""

import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from satchel_agent.agent import ShoppingAgent
from satchel_agent.server import create_app
from satchel_agent.tools import ToolBox

from .test_agent import ScriptedClient, make_message, tool_use
from anthropic.types import TextBlock


def parse_sse(body: str) -> list[dict]:
    return [
        json.loads(chunk[6:])
        for chunk in body.split("\n\n")
        if chunk.startswith("data: ")
    ]


def build(script):
    client = ScriptedClient(script)
    agent = ShoppingAgent(
        client,
        lambda sid, aid: ToolBox(None, None, None, aid, session_id=sid),
    )
    return agent


def test_chat_streams_sse(tmp_path):
    agent = build(lambda m: make_message(TextBlock(type="text", text="hi!")))
    sessions = {}
    client = TestClient(create_app(agent, sessions))
    response = client.post("/chat", json={"message": "hello"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = parse_sse(response.text)
    assert events[0]["type"] == "session"
    assert events[1:] == [
        {"type": "text", "delta": "hi!"},
        {"type": "done"},
    ]
    session_id = events[0]["session_id"]
    assert session_id in sessions


def test_session_reuse_and_history(tmp_path):
    agent = build(lambda m: make_message(TextBlock(type="text", text="ok")))
    sessions = {}
    client = TestClient(create_app(agent, sessions))
    first = parse_sse(client.post("/chat", json={"message": "one"}).text)
    sid = first[0]["session_id"]
    second = parse_sse(
        client.post("/chat", json={"message": "two", "session_id": sid}).text
    )
    assert second[0]["session_id"] == sid
    view = client.get(f"/sessions/{sid}").json()
    assert view["agent_id"] == sessions[sid].agent_id
    assert [m["text"] for m in view["messages"]] == ["one", "ok", "two", "ok"]
    assert view["budget"] == {"has_budget": False}
    assert client.get("/sessions/deadbeef").status_code == 404
    log_path = Path(os.environ["SATCHEL_EVENT_LOG"])
    log = log_path.read_text() if log_path.exists() else ""
    assert '"tool_call"' not in log


def test_busy_session_returns_409(tmp_path):
    agent = build(lambda m: make_message(TextBlock(type="text", text="ok")))
    sessions = {}
    client = TestClient(create_app(agent, sessions))
    first = parse_sse(client.post("/chat", json={"message": "hi"}).text)
    session = sessions[first[0]["session_id"]]
    session.lock.acquire()
    try:
        response = client.post(
            "/chat",
            json={"message": "again", "session_id": session.session_id},
        )
        assert response.status_code == 409
    finally:
        session.lock.release()


def test_unread_response_does_not_leave_session_locked(tmp_path):
    agent = build(lambda m: make_message(TextBlock(type="text", text="ok")))
    sessions = {}
    client = TestClient(create_app(agent, sessions))
    first = parse_sse(client.post("/chat", json={"message": "hi"}).text)
    sid = first[0]["session_id"]
    with client.stream(
        "POST", "/chat", json={"message": "unread", "session_id": sid}
    ) as response:
        assert response.status_code == 200
    assert not sessions[sid].lock.locked()
    retry = client.post("/chat", json={"message": "ok", "session_id": sid})
    assert retry.status_code == 200
    events = parse_sse(retry.text)
    assert events[-1] == {"type": "done"}
