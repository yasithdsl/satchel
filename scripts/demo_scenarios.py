"""Run the three demo scenarios against the running demo stack."""

import json
import sys
import threading
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))

import demo_stack
from demo_stack import (
    AGENT_URL,
    APPROVER_URL,
    EVENT_LOG,
    LOG_DIR,
    SPECULOS_URL,
    XRAY_URL,
)

CHAT_TIMEOUT = httpx.Timeout(600.0, connect=10.0)

# The scripted user messages; the web presenter drawer sends the same ones.
SCENE1_ASK = "Find me headphones under $200 that arrive by Friday."
SCENE1_BUY = "Buy the Aurora ANC Wireless Headphones."
SCENE2_ASK = "Get me a $200 budget for today."
SCENE3_ASK = "Get me a $100 budget for today."
SCENE3_BUY = "Buy me the Featherbook 13 laptop."
ATTACK_REQUEST_SATS = 5_000_000


class Transcript:
    def __init__(self, path: Path):
        self._fh = open(path, "w")
        self._text = ""

    def line(self, text: str = "") -> None:
        print(text)
        self._fh.write(text + "\n")
        self._fh.flush()

    def user(self, message: str) -> None:
        self.line(f"USER: {message}")

    def event(self, event: dict) -> None:
        kind = event.get("type")
        if kind == "text":
            self._text += event.get("delta", "")
            return
        self.flush_text()
        if kind == "tool_call":
            self.line(
                f"  -> tool {event.get('name')} "
                f"{json.dumps(event.get('input'))}"
            )
        elif kind == "notice":
            self.line(f"NOTICE: {event.get('text')}")
        elif kind == "tool_result":
            result = json.dumps(event.get("result"))
            self.line(f"  <- {event.get('name')} {result[:600]}")
        elif kind == "error":
            self.line(f"ERROR: {event.get('error')}")

    def flush_text(self) -> None:
        if self._text:
            self.line(f"CLAUDE: {self._text}")
            self._text = ""

    def close(self) -> None:
        self.flush_text()
        self._fh.close()


def chat_turn(message: str, session_id: str | None, transcript: Transcript):
    events = []
    transcript.user(message)
    with httpx.stream(
        "POST",
        f"{AGENT_URL}/chat",
        json={"message": message, "session_id": session_id},
        timeout=CHAT_TIMEOUT,
    ) as response:
        response.raise_for_status()
        for line in response.iter_lines():
            if line.startswith("data: "):
                event = json.loads(line[6:])
                events.append(event)
                transcript.event(event)
    transcript.flush_text()
    return events


def tool_results(events: list[dict], name: str) -> list[dict]:
    return [
        e.get("result") or {}
        for e in events
        if e.get("type") == "tool_result" and e.get("name") == name
    ]


def session_id_of(events: list[dict]) -> str | None:
    for e in events:
        if e.get("type") == "session":
            return e.get("session_id")
    return None


def get_json(url: str, timeout: int = 30) -> dict:
    status, body = demo_stack.http_json(url, timeout=timeout)
    if status != 200:
        raise RuntimeError(f"GET {url} -> {status}: {body}")
    return body


def post_json(url: str, body: dict, timeout: int = 300) -> dict:
    status, out = demo_stack.http_json(url, body, timeout=timeout)
    if status != 200:
        raise RuntimeError(f"POST {url} -> {status}: {out}")
    return out


def mine_block() -> None:
    post_json(f"{XRAY_URL}/demo/mine", {})


def wait_until(predicate, timeout: float = 30.0, interval: float = 1.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


def event_log_offset() -> int:
    if not EVENT_LOG.exists():
        return 0
    return sum(1 for _ in open(EVENT_LOG))


def read_events(offset: int = 0) -> list[dict]:
    if not EVENT_LOG.exists():
        return []
    lines = EVENT_LOG.read_text().splitlines()[offset:]
    out = []
    for line in lines:
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def choose_decision(expected: deque) -> tuple[str, bool]:
    if expected:
        return expected.popleft(), False
    return "reject", True


class Decider(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self.expected: deque[str] = deque()
        self.records: list[dict] = []
        self.errors: list[str] = []
        self._handled: set[str] = set()
        self._stop = threading.Event()

    def expect(self, *decisions: str) -> None:
        self.expected.extend(decisions)

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> None:
        while not self._stop.is_set():
            pending = None
            try:
                _, body = demo_stack.http_json(
                    f"{APPROVER_URL}/pending", timeout=5
                )
                pending = body.get("pending")
            except Exception:
                pass
            if pending and pending.get("nonce") not in self._handled:
                self._handled.add(pending["nonce"])
                self._handle(pending)
            time.sleep(0.25)

    def _review_up(self, timeout: float = 30.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                _, body = demo_stack.http_json(
                    f"{SPECULOS_URL}/events?currentscreenonly=true",
                    timeout=5,
                )
                texts = [e.get("text", "") for e in body.get("events", [])]
                if texts and "Ethereum" not in texts:
                    return True
            except Exception:
                pass
            time.sleep(0.3)
        return False

    def _handle(self, pending: dict) -> None:
        if not self._review_up():
            self.errors.append(
                f"review screen never appeared for nonce "
                f"{pending.get('nonce')}"
            )
        decision, unexpected = choose_decision(self.expected)
        if unexpected:
            self.errors.append(
                f"unexpected {pending.get('kind')} approval "
                f"(nonce {pending.get('nonce')}); rejected"
            )
        self.records.append(
            {
                "nonce": pending.get("nonce"),
                "kind": pending.get("kind"),
                "text": pending.get("text"),
                "decision": decision,
            }
        )
        try:
            demo_stack.http_json(
                f"{APPROVER_URL}/demo/{decision}", {}, timeout=60
            )
        except Exception as exc:
            self.errors.append(
                f"/demo/{decision} failed for nonce "
                f"{pending.get('nonce')}: {exc}"
            )


class Failures:
    def __init__(self):
        self.items: list[str] = []

    def check(self, condition, message: str) -> None:
        if not condition:
            self.items.append(message)

    def __bool__(self):
        return bool(self.items)


def scenario_normal_purchase(t: Transcript, decider: Decider):
    f = Failures()
    decider.expect("approve")
    events = chat_turn(SCENE1_ASK, None, t)
    session_id = session_id_of(events)
    f.check(session_id is not None, "no session id returned")
    budgets = tool_results(events, "request_budget")
    f.check(len(budgets) == 1, "request_budget was not called once")
    budget = budgets[0] if budgets else {}
    f.check(budget.get("granted") is True, "request_budget not granted")
    f.check(
        budget.get("budget_sats") == 200_000,
        f"request_budget granted {budget.get('budget_sats')} != 200000",
    )
    f.check(
        budget.get("envelope_index") == 0,
        f"scene 1 used satchel {budget.get('envelope_index')}, not the "
        f"first one (#0)",
    )
    if session_id:
        session = get_json(f"{AGENT_URL}/sessions/{session_id}")
        agent_id = session.get("agent_id")
        state = get_json(f"{XRAY_URL}/state")
        envelope = next(
            (
                e
                for e in state.get("envelopes") or []
                if e.get("index") == 0
            ),
            {},
        )
        f.check(
            envelope.get("assigned_to") == agent_id,
            f"200000 envelope assigned to {envelope.get('assigned_to')} "
            f"not {agent_id}",
        )

    events = chat_turn(SCENE1_BUY, session_id, t)
    buys = tool_results(events, "buy_product")
    if not buys:
        events = chat_turn("Yes, please buy them.", session_id, t)
        buys = tool_results(events, "buy_product")
    buy = buys[-1] if buys else {}
    f.check(buys, "buy_product was never called")
    f.check(
        buy.get("status") == "paid_from_budget",
        f"buy_product status {buy.get('status')} != paid_from_budget",
    )
    f.check(
        buy.get("amount_sats") == 179_000,
        f"buy_product amount {buy.get('amount_sats')} != 179000",
    )
    order_id = buy.get("order_id")
    if order_id:
        mine_block()

        def paid():
            try:
                return (
                    get_json(f"{AGENT_URL}/orders/{order_id}").get("status")
                    == "paid"
                )
            except Exception:
                return False

        f.check(
            wait_until(paid, timeout=30),
            f"order {order_id} never reached paid",
        )
    return session_id, f


def scenario_compromise(t: Transcript, decider: Decider):
    """A fresh agent gets a fresh $200 satchel, then is fully compromised."""
    f = Failures()
    records_start = len(decider.records)
    decider.expect("approve")
    events = chat_turn(SCENE2_ASK, None, t)
    session_id = session_id_of(events)
    budgets = tool_results(events, "request_budget")
    budget = budgets[-1] if budgets else {}
    f.check(
        budget.get("granted") is True and budget.get("budget_sats") == 200_000,
        f"request_budget got {budget.get('budget_sats')}, "
        f"granted={budget.get('granted')}",
    )
    f.check(
        budget.get("envelope_index") == 1,
        f"scene 2 used satchel {budget.get('envelope_index')}, not a fresh "
        f"second one (#1)",
    )
    if session_id is None:
        f.check(False, "no session id returned")
        return f
    agent_id = get_json(f"{AGENT_URL}/sessions/{session_id}").get("agent_id")

    offset = event_log_offset()
    state = get_json(f"{XRAY_URL}/state")
    envelope = next(
        (
            e
            for e in state.get("envelopes") or []
            if e.get("assigned_to") == agent_id
        ),
        {},
    )
    balance_before = envelope.get("balance_sats") or 0
    f.check(
        balance_before == 200_000,
        f"compromised agent's budget holds {balance_before}, not an "
        f"untouched 200000",
    )
    main_before = (state.get("main_funds") or {}).copy()
    sink_before = (state.get("loss_sink") or {}).get("confirmed_sats") or 0

    decider.expect("reject")
    t.line(f"POST /demo/compromise session={session_id}")
    report = post_json(
        f"{AGENT_URL}/demo/compromise",
        {"session_id": session_id, "request_sats": ATTACK_REQUEST_SATS},
        timeout=300,
    )
    t.line(f"  <- compromise {json.dumps(report)[:600]}")
    drained = report.get("drained_sats") or 0
    f.check(drained > 0, "compromise drained nothing")
    f.check(
        drained <= balance_before,
        f"drained {drained} exceeds envelope balance {balance_before}",
    )
    f.check(
        drained >= balance_before - 2_000,
        f"drained {drained}: the attacker should take the whole budget "
        f"less the fee",
    )
    large = report.get("large_spend") or {}
    f.check(
        not large.get("broadcast"),
        "compromise large spend was broadcast",
    )
    f.check(
        large.get("stage") == "approval",
        f"large spend stage {large.get('stage')} != approval",
    )
    decisions = decider.records[records_start:]
    f.check(
        [(d["kind"], d["decision"]) for d in decisions]
        == [("satchel_grant", "approve"), ("large_spend", "reject")],
        f"Ledger decisions were "
        f"{[(d['kind'], d['decision']) for d in decisions]}",
    )
    events = read_events(offset)
    f.check(
        any(e.get("type") == "compromise_large_spend_blocked" for e in events),
        "no compromise_large_spend_blocked event",
    )
    started = next(
        (
            i
            for i, e in enumerate(events)
            if e.get("type") == "compromise_started"
        ),
        len(events),
    )
    f.check(
        not any(
            e.get("type") == "spend_keys_released"
            for e in events[started:]
        ),
        "vault released spend keys after the compromise started",
    )
    mine_block()
    state = get_json(f"{XRAY_URL}/state")
    sink_after = (state.get("loss_sink") or {}).get("confirmed_sats") or 0
    f.check(
        sink_after == sink_before + drained,
        f"loss sink {sink_after} != {sink_before} + {drained}",
    )
    main_after = state.get("main_funds") or {}
    f.check(
        main_after.get("balance_sats") == main_before.get("balance_sats")
        and main_after.get("available_sats")
        == main_before.get("available_sats"),
        "main funds changed during the compromise",
    )
    return f


def scenario_random_nonce(t: Transcript, decider: Decider):
    """A $100 satchel (honest signer), then the signer turns malicious and the
    vault blocks the over-budget purchase from main funds."""
    f = Failures()
    decider.expect("approve")
    events = chat_turn(SCENE3_ASK, None, t)
    session_id = session_id_of(events)
    budgets = tool_results(events, "request_budget")
    budget = budgets[0] if budgets else {}
    f.check(
        budget.get("granted") is True
        and budget.get("budget_sats") == 100_000,
        f"request_budget got {budget.get('budget_sats')}, "
        f"granted={budget.get('granted')}",
    )
    f.check(
        budget.get("envelope_index") == 2,
        f"scene 3 used satchel {budget.get('envelope_index')}, not a fresh "
        f"third one (#2)",
    )
    post_json(f"{XRAY_URL}/demo/random-nonce", {"enabled": True})
    try:
        offset = event_log_offset()
        state = get_json(f"{XRAY_URL}/state")
        main_before = (state.get("main_funds") or {}).copy()

        decider.expect("approve")
        events = chat_turn(SCENE3_BUY, session_id, t)
        buys = tool_results(events, "buy_product")
        large = tool_results(events, "request_large_purchase")
        if not large:
            events = chat_turn("Yes, go ahead.", session_id, t)
            buys += tool_results(events, "buy_product")
            large = tool_results(events, "request_large_purchase")
        result = large[-1] if large else {}
        f.check(large, "request_large_purchase was never called")
        f.check(
            result.get("paid") is False,
            f"large purchase paid={result.get('paid')}",
        )
        f.check(
            result.get("stage") == "verification",
            f"large purchase stage {result.get('stage')} != verification",
        )
        f.check(
            "deterministic" in (result.get("reason") or ""),
            f"reason {result.get('reason')!r} does not mention "
            f"deterministic",
        )
        events_log = read_events(offset)
        f.check(
            any(
                e.get("type") == "verification_failed"
                and e.get("component") == "vault"
                for e in events_log
            ),
            "no vault verification_failed event",
        )
        exceeds = [
            r for r in buys if r.get("status") == "exceeds_budget"
        ]
        order_id = (
            exceeds[-1].get("order_id")
            if exceeds
            else result.get("order_id")
        )
        if order_id:
            mine_block()
            order = get_json(f"{AGENT_URL}/orders/{order_id}")
            f.check(
                order.get("status") != "paid",
                f"order {order_id} became paid: {order.get('status')}",
            )
        main_after = get_json(f"{XRAY_URL}/state").get("main_funds") or {}
        f.check(
            main_after.get("balance_sats") == main_before.get("balance_sats")
            and main_after.get("available_sats")
            == main_before.get("available_sats"),
            "main funds changed",
        )
    finally:
        post_json(f"{XRAY_URL}/demo/random-nonce", {"enabled": False})
    return f


def services_healthy() -> list[str]:
    problems = []
    for service in demo_stack.services():
        try:
            status, _ = demo_stack.http_json(
                f"{service.url}/health", timeout=3
            )
            if status != 200:
                problems.append(f"{service.name} /health -> {status}")
        except Exception as exc:
            problems.append(f"{service.name} unreachable: {exc}")
    return problems


def main() -> int:
    problems = services_healthy()
    if problems:
        for p in problems:
            print(f"  FAIL: {p}")
        print("run `uv run scripts/demo_reset.py` first")
        return 1
    state = get_json(f"{XRAY_URL}/state")
    problems = demo_stack.start_state_problems(state)
    if problems:
        for p in problems:
            print(f"  FAIL: {p}")
        print("stack is not in the start state; run `uv run scripts/demo_reset.py`")
        return 1

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    transcript_path = LOG_DIR / f"scenarios-{stamp}.txt"
    t = Transcript(transcript_path)
    decider = Decider()
    decider.start()
    results = {}
    try:
        try:
            t.line("SCENARIO 1: normal purchase")
            _session_id, f1 = scenario_normal_purchase(t, decider)
            results["normal purchase"] = f1.items
        except Exception as exc:
            results["normal purchase"] = [f"crashed: {exc}"]

        try:
            t.line("\nSCENARIO 2: simulated compromise of a fresh $200 budget")
            f2 = scenario_compromise(t, decider)
            results["simulated compromise"] = f2.items
        except Exception as exc:
            results["simulated compromise"] = [f"crashed: {exc}"]

        try:
            t.line("\nSCENARIO 3: random-nonce signer blocked")
            f3 = scenario_random_nonce(t, decider)
            results["random-nonce signer blocked"] = f3.items
        except Exception as exc:
            results["random-nonce signer blocked"] = [f"crashed: {exc}"]
    finally:
        decider.stop()
        for error in decider.errors:
            t.line(f"decider error: {error}")
        if decider.records:
            t.line("\nLedger decisions:")
            for r in decider.records:
                t.line(
                    f"  {r['decision']:7} {r['kind']} "
                    f"nonce={r['nonce']} :: {r['text']}"
                )
        t.line(f"\ntranscript: {transcript_path}")
        t.close()

    overall = 0
    for name, failures in results.items():
        if failures:
            overall = 1
            print(f"FAIL {name}: {failures[0]}")
        else:
            print(f"PASS {name}")
    return overall


if __name__ == "__main__":
    sys.exit(main())
