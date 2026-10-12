"""Restore the demo to its known start state and leave the stack running."""

import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import demo_stack
from demo_stack import (
    AGENT_URL,
    APPROVER_URL,
    DEMO_PASSPHRASE,
    DEMO_PORTS,
    EVENT_LOG,
    LAPTOP_DIR,
    LAPTOP_URL,
    LOG_DIR,
    MARKETPLACE_DIR,
    MARKETPLACE_URL,
    REPO,
    RUN_DIR,
    SATCHEL_DIR,
    SIGNER_URL,
    SPECULOS_URL,
    VAULT_DIR,
    VAULT_URL,
    XRAY_URL,
)

COMPOSE_FILE = REPO / "docker-compose.yml"


def fail(message: str) -> None:
    sys.exit(f"demo reset failed: {message}")


def step(title: str) -> None:
    print(f"\n== {title} ==")


def compose(*args: str) -> None:
    try:
        subprocess.run(
            ["docker", "compose", "-f", str(COMPOSE_FILE), *args], check=True
        )
    except subprocess.CalledProcessError as exc:
        fail(f"docker compose {' '.join(args)} exited {exc.returncode}")


def wait_speculos_home(timeout: float = 90) -> list[str]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            status, body = demo_stack.http_json(
                f"{SPECULOS_URL}/events?currentscreenonly=true", timeout=3
            )
            texts = [e.get("text", "") for e in body.get("events", [])]
            if status == 200 and "Ethereum" in texts:
                return texts
        except Exception:
            pass
        time.sleep(0.5)
    fail("Speculos never reached the Ethereum home screen")


def preconditions() -> None:
    step("preconditions")
    result = subprocess.run(
        ["docker", "info"], capture_output=True, text=True
    )
    if result.returncode != 0:
        fail("Docker is not reachable")
    if not list((REPO / "approver" / "apps").glob("*.elf")):
        print("fetching the Ethereum app ELF")
        subprocess.run(
            ["bash", "approver/scripts/fetch-eth-app.sh"],
            cwd=REPO,
            check=True,
        )
    if not (REPO / "approver" / "node_modules").exists():
        print("installing approver dependencies")
        subprocess.run(
            ["pnpm", "install", "--frozen-lockfile"],
            cwd=REPO / "approver",
            check=True,
        )
    if not (REPO / ".env").exists():
        print(
            "warning: .env is missing; the agent cannot call Claude and "
            "the shopping scenarios will fail"
        )


def stop_and_check_ports() -> None:
    step("stop demo services")
    ours = demo_stack.demo_pids()
    demo_stack.stop_all()
    time.sleep(0.5)
    for port in DEMO_PORTS:
        pid = demo_stack.port_pid(port)
        if pid is not None and pid not in ours:
            fail(
                f"port {port} is in use by pid {pid}, which is not a demo "
                f"service; free it and retry (never killing unknown processes)"
            )
        if pid is not None:
            fail(
                f"demo service on port {port} (pid {pid}) did not stop; "
                f"check {LOG_DIR}"
            )


def wipe_state() -> None:
    step("wipe demo state")
    for path in (VAULT_DIR, LAPTOP_DIR, MARKETPLACE_DIR):
        shutil.rmtree(path, ignore_errors=True)
    EVENT_LOG.unlink(missing_ok=True)
    shutil.rmtree(RUN_DIR, ignore_errors=True)
    shutil.rmtree(LOG_DIR, ignore_errors=True)
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)


def fresh_chain_and_ledger() -> None:
    step("fresh regtest chain and Ledger")
    compose("--profile", "ledger", "down", "-v")
    compose("--profile", "ledger", "up", "-d", "--wait")
    wait_speculos_home()
    print("Speculos is on the Ethereum home screen")


def reset() -> None:
    preconditions()
    stop_and_check_ports()
    wipe_state()
    fresh_chain_and_ledger()

    from satchel_core.regtest import RegtestNode

    node = RegtestNode.from_env()
    node.ensure_faucet()

    os.environ["SATCHEL_EVENT_LOG"] = str(EVENT_LOG)
    os.environ["SATCHEL_VAULT_DIR"] = str(VAULT_DIR)
    os.environ["SATCHEL_LAPTOP_DIR"] = str(LAPTOP_DIR)
    os.environ["SATCHEL_MARKETPLACE_DIR"] = str(MARKETPLACE_DIR)

    by_name = {s.name: s for s in demo_stack.services()}

    step("approver")
    proc = demo_stack.start_service(by_name["approver"])
    demo_stack.wait_health(f"{APPROVER_URL}/health", timeout=60, proc=proc)
    status, address = demo_stack.http_json(f"{APPROVER_URL}/address")
    if status != 200:
        fail(f"approver /address returned {status}: {address}")
    ledger_address = address["address"]
    print(f"Ledger address: {ledger_address}")

    step("vault")
    from satchel_vault.vault import Vault

    vault = Vault(VAULT_DIR)
    fingerprint = vault.setup_with_demo_seed(DEMO_PASSPHRASE, ledger_address)
    vault.unlock(DEMO_PASSPHRASE)
    vault.allocate_demo_envelopes()
    print(f"vault fingerprint {fingerprint}; demo envelopes allocated")
    proc = demo_stack.start_service(by_name["vault"])
    demo_stack.wait_health(f"{VAULT_URL}/health", timeout=30, proc=proc)

    step("funding")
    from satchel_laptop.funding import fund_envelopes
    from satchel_laptop.main_funds import fund_main_funds
    from satchel_laptop.state import LaptopState
    from satchel_laptop.vault_client import VaultClient

    state = LaptopState.from_env()
    client = VaultClient(VAULT_URL)
    funded_envelopes = fund_envelopes(client, node, state)
    funded_main = fund_main_funds(client, node, state)
    print(
        f"funded {len(funded_envelopes)} envelopes and "
        f"{len(funded_main)} main-funds addresses"
    )

    step("services")
    for name in ("signer", "laptop", "marketplace", "agent", "xray"):
        proc = demo_stack.start_service(by_name[name])
        demo_stack.wait_health(
            f"{by_name[name].url}/health", timeout=60, proc=proc
        )
        print(f"{name} is up at {by_name[name].url}")

    step("verify start state")
    status, state_snapshot = demo_stack.http_json(f"{XRAY_URL}/state")
    if status != 200:
        fail(f"x-ray /state returned {status}")
    problems = demo_stack.start_state_problems(state_snapshot)
    if problems:
        for problem in problems:
            print(f"  FAIL: {problem}")
        fail("start state is not clean; check the service logs in .satchel/logs")
    print("start state is clean")

    envelopes = state_snapshot["envelopes"]
    print("\nDemo stack is running:")
    for name in ("laptop", "vault", "signer", "approver", "marketplace", "agent", "xray"):
        print(f"  {name:12} {by_name[name].url}")
    print(f"  {'ledger':12} {ledger_address}")
    print(f"  {'speculos':12} {SPECULOS_URL}")
    print(
        f"  envelopes: "
        + ", ".join(
            f"#{e['index']} {e['budget_sats']} sats" for e in envelopes
        )
    )
    print(
        f"  main funds: "
        f"{state_snapshot['main_funds']['available_sats']} sats available"
    )
    print("\nWeb app: cd web && pnpm dev  →  http://localhost:3100")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--stop", action="store_true", help="stop demo services only"
    )
    args = parser.parse_args()
    if args.stop:
        demo_stack.stop_all()
        print("demo services stopped")
        return
    reset()


if __name__ == "__main__":
    main()
