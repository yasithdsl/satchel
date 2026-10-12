"""Shared helpers for the demo scripts: service table, lifecycle, HTTP."""

import json
import os
import shutil
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SATCHEL_DIR = REPO / ".satchel"
RUN_DIR = SATCHEL_DIR / "run"
LOG_DIR = SATCHEL_DIR / "logs"
EVENT_LOG = SATCHEL_DIR / "events.jsonl"
VAULT_DIR = SATCHEL_DIR / "vault"
LAPTOP_DIR = SATCHEL_DIR / "laptop"
MARKETPLACE_DIR = SATCHEL_DIR / "marketplace"

DEMO_PASSPHRASE = "satchel demo passphrase"

LAPTOP_URL = "http://127.0.0.1:8000"
VAULT_URL = "http://127.0.0.1:8001"
SIGNER_URL = "http://127.0.0.1:8002"
APPROVER_URL = "http://127.0.0.1:8003"
MARKETPLACE_URL = "http://127.0.0.1:8004"
AGENT_URL = "http://127.0.0.1:8005"
XRAY_URL = "http://127.0.0.1:8006"
SPECULOS_URL = os.environ.get("SPECULOS_URL", "http://127.0.0.1:5001")

DEMO_PORTS = (8000, 8001, 8002, 8003, 8004, 8005, 8006)
MAIN_FUNDS_SATS = 100_000_000
DEMO_ENVELOPE_BUDGETS = (100_000, 200_000, 500_000)


def console_script(name: str) -> str:
    candidate = Path(sys.executable).parent / name
    if candidate.exists():
        return str(candidate)
    found = shutil.which(name)
    if found:
        return found
    raise RuntimeError(f"cannot find {name}; run via `uv run`")


def _agent_command() -> list[str]:
    if (REPO / ".env").exists():
        return [
            "uv",
            "run",
            "--env-file",
            ".env",
            "satchel-agent",
            "serve",
        ]
    return [console_script("satchel-agent"), "serve"]


@dataclass
class Service:
    name: str
    cmd: list[str]
    port: int
    health: str = "/health"
    env: dict = field(default_factory=dict)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"


def services() -> list[Service]:
    return [
        Service(
            "approver",
            ["node", "approver/src/main.ts"],
            8003,
            env={
                "APPROVER_PORT": "8003",
                "SATCHEL_APPROVER_DEMO_AUTOMATION": "1",
            },
        ),
        Service(
            "vault",
            [console_script("satchel-vault"), "serve"],
            8001,
            env={
                "SATCHEL_VAULT_PASSPHRASE": DEMO_PASSPHRASE,
                "SATCHEL_VAULT_DIR": str(VAULT_DIR),
            },
        ),
        Service("signer", [console_script("satchel-signer"), "serve"], 8002),
        Service(
            "laptop",
            [console_script("satchel-laptop"), "serve"],
            8000,
            env={"SATCHEL_LAPTOP_DIR": str(LAPTOP_DIR)},
        ),
        Service(
            "marketplace",
            [console_script("satchel-marketplace"), "serve"],
            8004,
            env={"SATCHEL_MARKETPLACE_DIR": str(MARKETPLACE_DIR)},
        ),
        Service(
            "agent",
            _agent_command(),
            8005,
            env={"SATCHEL_AGENT_DEMO_CONTROLS": "1"},
        ),
        Service(
            "xray",
            [console_script("satchel-xray"), "serve"],
            8006,
            env={"SATCHEL_LAPTOP_DIR": str(LAPTOP_DIR)},
        ),
    ]


def http_json(url: str, body=None, timeout: int = 30):
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(
        url,
        data=data,
        headers={"content-type": "application/json"} if data else {},
        method="POST" if data is not None else "GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, json.loads(exc.read())
        except Exception:
            return exc.code, {}


def start_service(service: Service) -> subprocess.Popen:
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log = open(LOG_DIR / f"{service.name}.log", "ab")
    env = {
        **os.environ,
        **service.env,
        "SATCHEL_EVENT_LOG": str(EVENT_LOG),
    }
    proc = subprocess.Popen(
        service.cmd,
        cwd=REPO,
        env=env,
        stdout=log,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    log.close()
    (RUN_DIR / f"{service.name}.pid").write_text(str(proc.pid))
    return proc


def _pid_running(pid: int) -> bool:
    try:
        os.killpg(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def stop_service(name: str) -> bool:
    pid_file = RUN_DIR / f"{name}.pid"
    if not pid_file.exists():
        return False
    try:
        pid = int(pid_file.read_text().strip())
    except ValueError:
        pid_file.unlink()
        return False
    pid_file.unlink()
    try:
        os.killpg(pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        return True
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if not _pid_running(pid):
            return True
        time.sleep(0.2)
    try:
        os.killpg(pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass
    return True


def stop_all(names=None) -> None:
    for name in names or [s.name for s in services()]:
        if stop_service(name):
            print(f"stopped {name}")


def port_pid(port: int) -> int | None:
    result = subprocess.run(
        ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-Fp"],
        capture_output=True,
        text=True,
    )
    for line in result.stdout.splitlines():
        if line.startswith("p"):
            try:
                return int(line[1:])
            except ValueError:
                continue
    return None


def demo_pids() -> set[int]:
    pids = set()
    for path in RUN_DIR.glob("*.pid"):
        try:
            pids.add(int(path.read_text().strip()))
        except ValueError:
            continue
    return pids


def wait_health(url: str, timeout: float = 60, proc=None) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc is not None and proc.poll() is not None:
            raise RuntimeError(
                f"{url} never became healthy; process exited with "
                f"{proc.returncode}"
            )
        try:
            status, _ = http_json(url, timeout=2)
            if status == 200:
                return
        except Exception:
            pass
        time.sleep(0.4)
    raise RuntimeError(f"{url} did not become healthy in {timeout}s")


def start_state_problems(state: dict) -> list[str]:
    problems = []
    if state.get("errors"):
        problems.append(f"state errors: {state['errors']}")
    main_funds = state.get("main_funds") or {}
    available = main_funds.get("available_sats")
    if available != MAIN_FUNDS_SATS:
        problems.append(
            f"main funds available {available} != {MAIN_FUNDS_SATS} sats"
        )
    envelopes = state.get("envelopes") or []
    if len(envelopes) != len(DEMO_ENVELOPE_BUDGETS):
        problems.append(
            f"expected {len(DEMO_ENVELOPE_BUDGETS)} envelopes, "
            f"got {len(envelopes)}"
        )
    else:
        for envelope, budget in zip(
            sorted(envelopes, key=lambda e: e.get("index", 0)),
            DEMO_ENVELOPE_BUDGETS,
        ):
            idx = envelope.get("index")
            if envelope.get("budget_sats") != budget:
                problems.append(
                    f"envelope {idx} budget "
                    f"{envelope.get('budget_sats')} != {budget}"
                )
            if envelope.get("status") != "unassigned":
                problems.append(
                    f"envelope {idx} status "
                    f"{envelope.get('status')!r} != 'unassigned'"
                )
            if envelope.get("assigned_to") is not None:
                problems.append(
                    f"envelope {idx} already assigned to "
                    f"{envelope.get('assigned_to')}"
                )
            if envelope.get("balance_sats") != budget:
                problems.append(
                    f"envelope {idx} balance "
                    f"{envelope.get('balance_sats')} != {budget}"
                )
    sink = state.get("loss_sink")
    if sink is None:
        problems.append("loss sink not configured")
    else:
        total = (sink.get("confirmed_sats") or 0) + (
            sink.get("pending_sats") or 0
        )
        if total != 0:
            problems.append(f"loss sink holds {total} sats, expected 0")
    if state.get("random_nonce_signer") is not False:
        problems.append("random-nonce signer is not off")
    if not (state.get("compromise_control") or {}).get("enabled"):
        problems.append("compromise control is not enabled")
    pending = state.get("pending_approval")
    if isinstance(pending, dict):
        pending = pending.get("pending")
    if pending is not None:
        problems.append("an approval is still pending")
    return problems
