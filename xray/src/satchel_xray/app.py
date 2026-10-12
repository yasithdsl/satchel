"""X-ray service: SSE event stream, state snapshot, demo proxies."""

import asyncio
import json
import os
from collections import deque
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from satchel_core.regtest import NodeUnavailable, RegtestNode

from .enrich import Enricher
from .state import service_urls, snapshot
from .tail import EventTailer

DEFAULT_WEB_ORIGINS = (
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:3100",
    "http://127.0.0.1:3100",
)
KEEPALIVE_SECONDS = 15.0
RING_SIZE = 2000


def web_origins() -> list[str]:
    raw = os.environ.get("SATCHEL_WEB_ORIGINS")
    if raw:
        origins = [o.strip() for o in raw.split(",") if o.strip()]
        if origins:
            return origins
    return list(DEFAULT_WEB_ORIGINS)


class RandomNonceRequest(BaseModel):
    enabled: bool


def create_app(
    tailer: EventTailer | None = None,
    enricher: Enricher | None = None,
    *,
    urls: dict | None = None,
    http=None,
    node=None,
    poll_interval: float = 0.25,
    keepalive: float = KEEPALIVE_SECONDS,
    origins: list[str] | None = None,
) -> FastAPI:
    tailer = tailer or EventTailer.from_env()
    enricher = enricher or Enricher()
    urls = urls or service_urls()
    ring: deque = deque(maxlen=RING_SIZE)
    subscribers: set[asyncio.Queue] = set()

    def pump() -> None:
        for raw in tailer.poll():
            event = enricher.enrich(raw)
            ring.append(event)
            for queue in list(subscribers):
                queue.put_nowait(event)

    async def poller() -> None:
        while True:
            pump()
            await asyncio.sleep(poll_interval)

    @asynccontextmanager
    async def lifespan(app):
        task = asyncio.create_task(poller())
        yield
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    app = FastAPI(title="satchel-xray", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=web_origins() if origins is None else origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.pump = pump
    app.state.ring = ring

    @app.get("/events")
    async def events(request: Request, backlog: int = 200):
        last_event_id = request.headers.get("last-event-id")
        resume_after = None
        if last_event_id is not None:
            try:
                resume_after = int(last_event_id)
            except ValueError:
                resume_after = 0

        queue: asyncio.Queue = asyncio.Queue()
        subscribers.add(queue)

        async def stream():
            try:
                pending = [
                    e
                    for e in ring
                    if e["seq"] > (resume_after or 0)
                ]
                if resume_after is None:
                    pending = pending[-backlog:] if backlog > 0 else []
                last_sent = resume_after or 0
                for event in pending:
                    last_sent = event["seq"]
                    yield (
                        f"id: {event['seq']}\n"
                        f"data: {json.dumps(event)}\n\n"
                    )
                while True:
                    try:
                        event = await asyncio.wait_for(
                            queue.get(), timeout=keepalive
                        )
                    except asyncio.TimeoutError:
                        yield ": keepalive\n\n"
                        continue
                    if event["seq"] <= last_sent:
                        continue
                    last_sent = event["seq"]
                    yield (
                        f"id: {event['seq']}\n"
                        f"data: {json.dumps(event)}\n\n"
                    )
            finally:
                subscribers.discard(queue)

        return StreamingResponse(stream(), media_type="text/event-stream")

    @app.get("/state")
    def state_endpoint():
        return snapshot(urls, http=http)

    @app.post("/demo/random-nonce")
    def random_nonce(request: RandomNonceRequest):
        client = http or httpx.Client(timeout=5.0)
        try:
            response = client.post(
                f"{urls['signer']}/demo/random-nonce",
                json={"enabled": request.enabled},
            )
        except httpx.HTTPError as exc:
            raise HTTPException(
                503, f"signer unreachable: {exc}"
            )
        if response.status_code != 200:
            raise HTTPException(
                502, f"signer returned {response.status_code}"
            )
        return {"enabled": response.json().get("enabled")}

    @app.post("/demo/mine")
    def mine():
        if node is None:
            raise HTTPException(503, "regtest node is not configured")
        try:
            address = node.faucet_address()
            blocks = node.mine_blocks(1, address)
        except NodeUnavailable as exc:
            raise HTTPException(503, f"bitcoind unreachable: {exc}")
        return {"block_hash": blocks[0] if blocks else None}

    @app.get("/health")
    def health():
        return {"ok": True}

    return app


def create_app_from_env() -> FastAPI:
    laptop_dir = Path(
        os.environ.get("SATCHEL_LAPTOP_DIR", ".satchel/laptop")
    )
    return create_app(
        EventTailer.from_env(),
        Enricher(flows_dir=laptop_dir / "flows"),
        node=RegtestNode.from_env(),
    )
