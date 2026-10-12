import json
import os
import shutil
import socket
import subprocess
import time
import urllib.request
from pathlib import Path

import pytest

from satchel_core.regtest import NodeUnavailable, RegtestNode

REPO = Path(__file__).resolve().parent
SPECULOS_URL = os.environ.get("SPECULOS_URL", "http://127.0.0.1:5001")


@pytest.fixture(autouse=True)
def _event_log(tmp_path, monkeypatch):
    monkeypatch.setenv("SATCHEL_EVENT_LOG", str(tmp_path / "events.jsonl"))


@pytest.fixture(scope="module")
def node():
    node = RegtestNode.from_env()
    try:
        node.ensure_faucet()
    except NodeUnavailable:
        pytest.skip("regtest bitcoind not running (uv run scripts/regtest.py up)")
    return node


def speculos_up() -> bool:
    try:
        with urllib.request.urlopen(
            f"{SPECULOS_URL}/events?currentscreenonly=true", timeout=3
        ) as response:
            return response.status == 200
    except Exception:
        return False


def free_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def http_json(url: str, body: dict | None = None, timeout: int = 180):
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(
        url,
        data=data,
        headers={"content-type": "application/json"} if data else {},
        method="POST" if data else "GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


@pytest.fixture(scope="module")
def approver(tmp_path_factory):
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    if not speculos_up():
        pytest.skip(f"Speculos not reachable at {SPECULOS_URL}")
    port = free_port()
    workdir = tmp_path_factory.mktemp("approver")
    log = open(workdir / "approver.log", "w")
    env = {
        **os.environ,
        "APPROVER_PORT": str(port),
        "SATCHEL_APPROVER_DEMO_AUTOMATION": "1",
        "SPECULOS_URL": SPECULOS_URL,
        "SATCHEL_EVENT_LOG": str(workdir / "events.jsonl"),
    }
    proc = subprocess.Popen(
        ["node", "approver/src/main.ts"],
        cwd=REPO,
        env=env,
        stdout=log,
        stderr=log,
    )
    base = f"http://127.0.0.1:{port}"
    try:
        for _ in range(120):
            if proc.poll() is not None:
                raise RuntimeError(
                    f"approver exited early: {(workdir / 'approver.log').read_text()}"
                )
            try:
                status, health = http_json(f"{base}/health", timeout=2)
                if status == 200:
                    break
            except Exception:
                pass
            time.sleep(0.5)
        else:
            raise RuntimeError("approver never became healthy")
        yield base
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
        log.close()
