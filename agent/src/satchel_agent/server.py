"""HTTP surface of the shopping agent: SSE chat over the model loop."""

import json
import os

import anthropic
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from typing import Literal

from satchel_core.regtest import RegtestNode

from .agent import Session, ShoppingAgent
from .clients import LaptopClient, MarketplaceClient
from .compromise import LossSink, simulate_compromise
from .tools import ToolBox


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None


class CompromiseRequest(BaseModel):
    session_id: str
    request_sats: int = Field(default=5_000_000, gt=0)
    demo_auto: Literal["approve", "reject"] | None = None


def _message_text(message: dict) -> str:
    content = message.get("content")
    if isinstance(content, str):
        return content
    parts = [
        block.get("text", "")
        for block in content or []
        if isinstance(block, dict) and block.get("type") == "text"
    ]
    return "".join(parts)


def create_app(
    agent: ShoppingAgent,
    sessions: dict,
    demo_controls: bool = False,
    sink: LossSink | None = None,
    laptop: LaptopClient | None = None,
) -> FastAPI:
    app = FastAPI(title="satchel-agent")

    def demo_ready():
        if not demo_controls:
            raise HTTPException(404, "demo controls disabled")
        if sink is None or laptop is None:
            raise HTTPException(
                503, "demo controls need a loss sink and a laptop client"
            )

    @app.post("/chat")
    def chat(request: ChatRequest):
        session = (
            sessions.get(request.session_id)
            if request.session_id
            else None
        )
        if session is None:
            session = agent.new_session()
            sessions[session.session_id] = session
        if session.lock.locked():
            raise HTTPException(409, "a turn is already in progress")

        def stream():
            yield "data: " + json.dumps(
                {
                    "type": "session",
                    "session_id": session.session_id,
                }
            ) + "\n\n"
            if not session.lock.acquire(blocking=False):
                yield "data: " + json.dumps(
                    {
                        "type": "error",
                        "error": "a turn is already in progress",
                    }
                ) + "\n\n"
                yield "data: " + json.dumps({"type": "done"}) + "\n\n"
                return
            try:
                for event in agent.run_turn(session, request.message):
                    yield "data: " + json.dumps(event) + "\n\n"
            finally:
                session.lock.release()

        return StreamingResponse(
            stream(), media_type="text/event-stream"
        )

    @app.get("/sessions/{session_id}")
    def get_session(session_id: str):
        session = sessions.get(session_id)
        if session is None:
            raise HTTPException(404, f"unknown session: {session_id}")
        return {
            "session_id": session.session_id,
            "agent_id": session.agent_id,
            "messages": [
                {"role": m.get("role"), "text": _message_text(m)}
                for m in session.messages
            ],
            "budget": session.toolbox.budget(),
        }

    @app.post("/demo/compromise")
    def demo_compromise(request: CompromiseRequest):
        demo_ready()
        session = sessions.get(request.session_id)
        if session is None:
            raise HTTPException(
                404, f"unknown session: {request.session_id}"
            )
        if session.lock.locked():
            raise HTTPException(409, "a turn is already in progress")
        with session.lock:
            return simulate_compromise(
                session.toolbox,
                laptop,
                sink,
                request_sats=request.request_sats,
                demo_auto=request.demo_auto,
            )

    @app.get("/demo/loss-sink")
    def demo_loss_sink():
        demo_ready()
        return {
            **sink.balance(),
            "last_address": sink.last_address,
        }

    @app.get("/health")
    def health():
        return {"ok": True}

    return app


def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").lower() in ("1", "true", "yes")


def create_app_from_env() -> FastAPI:
    node = RegtestNode.from_env()
    marketplace = MarketplaceClient()
    laptop = LaptopClient()
    demo_auto = os.environ.get("SATCHEL_AGENT_DEMO_AUTO") or None
    demo_controls = _env_flag("SATCHEL_AGENT_DEMO_CONTROLS")
    sink = None
    if demo_controls:
        sink = LossSink(node)
        sink.ensure()

    def toolbox_factory(session_id: str, agent_id: str) -> ToolBox:
        return ToolBox(
            marketplace,
            laptop,
            node,
            agent_id,
            session_id=session_id,
            demo_auto=demo_auto,
        )

    agent = ShoppingAgent(anthropic.Anthropic(), toolbox_factory)
    return create_app(
        agent, {}, demo_controls=demo_controls, sink=sink, laptop=laptop
    )
