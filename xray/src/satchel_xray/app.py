"""X-ray service: SSE event stream, state snapshot, demo proxies."""

import asyncio
import json
import os
import uuid
from collections import deque
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel

from satchel_core.events import emit
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


FINGER_ACTIONS = {"press", "release", "press-and-release"}
SCREEN_W = 480
SCREEN_H = 600


class FingerRequest(BaseModel):
    action: str
    x: float
    y: float
    x2: float | None = None
    y2: float | None = None
    delay: float | None = None

    def speculos_body(self) -> dict:
        if self.action not in FINGER_ACTIONS:
            raise HTTPException(422, f"unknown action {self.action!r}")
        if self.delay is not None and self.delay < 0:
            raise HTTPException(422, "delay must be >= 0")
        body = {"action": self.action}
        for name, bound in (
            ("x", SCREEN_W),
            ("x2", SCREEN_W),
            ("y", SCREEN_H),
            ("y2", SCREEN_H),
        ):
            raw = getattr(self, name)
            if raw is None:
                continue
            value = int(round(raw))
            if not 0 <= value < bound:
                raise HTTPException(
                    422, f"finger coordinate {name} outside 0..{bound}"
                )
            body[name] = value
        if self.delay is not None:
            body["delay"] = self.delay
        return body


def create_app(
    tailer: EventTailer | None = None,
    enricher: Enricher | None = None,
    *,
    urls: dict | None = None,
    http=None,
    node=None,
    speculos_url: str | None = None,
    poll_interval: float = 0.25,
    keepalive: float = KEEPALIVE_SECONDS,
    origins: list[str] | None = None,
) -> FastAPI:
    tailer = tailer or EventTailer.from_env()
    enricher = enricher or Enricher()
    urls = urls or service_urls()
    speculos_url = (
        speculos_url
        or os.environ.get("SATCHEL_SPECULOS_URL", "http://127.0.0.1:5001")
    ).rstrip("/")
    boot_id = uuid.uuid4().hex
    ring: deque = deque(maxlen=RING_SIZE)
    subscribers: set[asyncio.Queue] = set()

    def pump() -> None:
        for raw in tailer.poll():
            event = enricher.enrich(raw)
            event["boot"] = boot_id
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
        block_hash = blocks[0] if blocks else None
        emit(
            "network",
            "block_mined",
            "a block was mined",
            {"block_hash": block_hash},
        )
        return {"block_hash": block_hash}

    def _client():
        return http or httpx.Client(timeout=5.0)

    def _proxy_get(url: str):
        try:
            response = _client().get(url)
        except Exception as exc:
            raise HTTPException(503, f"upstream unreachable: {exc}")
        if response.status_code != 200:
            raise HTTPException(
                502, f"upstream returned {response.status_code}"
            )
        return response

    @app.get("/ledger/screenshot")
    def ledger_screenshot():
        response = _proxy_get(f"{speculos_url}/screenshot")
        return Response(
            content=response.content,
            media_type="image/png",
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/ledger/screen-text")
    def ledger_screen_text():
        response = _proxy_get(
            f"{speculos_url}/events?currentscreenonly=true"
        )
        body = response.json()
        texts = [
            e.get("text", "")
            for e in body.get("events", [])
            if isinstance(e, dict)
        ]
        return {"texts": texts}

    @app.post("/ledger/finger")
    def ledger_finger(request: FingerRequest):
        body = request.speculos_body()
        try:
            response = _client().post(
                f"{speculos_url}/finger", json=body
            )
        except Exception as exc:
            raise HTTPException(503, f"speculos unreachable: {exc}")
        if response.status_code != 200:
            raise HTTPException(
                502, f"speculos returned {response.status_code}"
            )
        return {"ok": True}

    def _ledger_action(action: str):
        try:
            response = _client().post(
                f"{urls['approver']}/demo/{action}",
                json={},
                timeout=30.0,
            )
        except Exception as exc:
            raise HTTPException(503, f"approver unreachable: {exc}")
        if response.status_code == 404:
            raise HTTPException(409, "automation is off")
        if response.status_code != 200:
            detail = ""
            try:
                detail = response.json().get("detail", "")
            except Exception:
                pass
            raise HTTPException(
                502, detail or f"approver returned {response.status_code}"
            )
        return {"ok": True}

    @app.post("/ledger/approve")
    def ledger_approve():
        return _ledger_action("approve")

    @app.post("/ledger/reject")
    def ledger_reject():
        return _ledger_action("reject")

    @app.get("/ledger/automation")
    def ledger_automation():
        response = _proxy_get(f"{urls['approver']}/health")
        return {
            "automation": bool(response.json().get("demo_automation"))
        }

    @app.get("/health")
    def health():
        return {"ok": True, "boot_id": boot_id}

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
