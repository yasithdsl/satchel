"""Unit tests for pure helpers in scripts/demo_stack.py and demo_scenarios.py."""

import importlib.util
from collections import deque
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _load(name):
    spec = importlib.util.spec_from_file_location(
        name, REPO / "scripts" / f"{name}.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


demo_stack = _load("demo_stack")
demo_scenarios = _load("demo_scenarios")


def clean_state():
    return {
        "ts": "now",
        "main_funds": {
            "fingerprint": "fp",
            "addresses": 3,
            "utxos": 3,
            "balance_sats": 100_000_000,
            "available_sats": 100_000_000,
        },
        "envelopes": [
            {
                "index": i,
                "budget_sats": b,
                "assigned_to": None,
                "status": "unassigned",
                "balance_sats": b,
            }
            for i, b in enumerate((100_000, 200_000, 500_000))
        ],
        "loss_sink": {
            "confirmed_sats": 0,
            "pending_sats": 0,
            "last_address": None,
        },
        "random_nonce_signer": False,
        "compromise_control": {"enabled": True},
        "pending_approval": None,
        "errors": {},
    }


def test_clean_start_state_has_no_problems():
    assert demo_stack.start_state_problems(clean_state()) == []


def test_start_state_flags_wrong_main_funds():
    state = clean_state()
    state["main_funds"]["available_sats"] = 90_000_000
    problems = demo_stack.start_state_problems(state)
    assert any("main funds" in p for p in problems)


def test_start_state_flags_envelope_problems():
    state = clean_state()
    state["envelopes"][1]["status"] = "assigned"
    state["envelopes"][2]["balance_sats"] = 0
    state["envelopes"][0]["assigned_to"] = "shopper-1"
    problems = demo_stack.start_state_problems(state)
    assert any("status" in p for p in problems)
    assert any("balance" in p for p in problems)
    assert any("assigned" in p for p in problems)


def test_start_state_flags_sink_nonce_pending_errors():
    state = clean_state()
    state["loss_sink"]["confirmed_sats"] = 100
    state["random_nonce_signer"] = True
    state["pending_approval"] = {"pending": {"kind": "spend"}}
    state["errors"] = {"agent": "down"}
    state["compromise_control"] = {"enabled": False}
    problems = demo_stack.start_state_problems(state)
    assert len(problems) == 5


def test_choose_decision_uses_expected_then_rejects():
    expected = deque(["approve"])
    assert demo_scenarios.choose_decision(expected) == ("approve", False)
    assert demo_scenarios.choose_decision(expected) == ("reject", True)


def test_wait_until_times_out():
    assert not demo_scenarios.wait_until(lambda: False, timeout=0.2, interval=0.05)
    calls = []

    def eventually():
        calls.append(1)
        return len(calls) >= 3

    assert demo_scenarios.wait_until(eventually, timeout=5, interval=0.01)


def test_tool_results_and_session_id():
    events = [
        {"type": "session", "session_id": "s1"},
        {"type": "tool_result", "name": "a", "result": {"x": 1}},
        {"type": "tool_result", "name": "b", "result": {"y": 2}},
    ]
    assert demo_scenarios.session_id_of(events) == "s1"
    assert demo_scenarios.tool_results(events, "a") == [{"x": 1}]


def test_transcript_format(tmp_path):
    t = demo_scenarios.Transcript(tmp_path / "t.txt")
    t.user("hello")
    for e in [
        {"type": "text", "delta": "Hi "},
        {"type": "text", "delta": "there"},
        {"type": "tool_call", "id": "t", "name": "search", "input": {"q": "x"}},
        {"type": "notice", "text": "approve on Ledger"},
        {"type": "tool_result", "id": "t", "name": "search", "result": {"n": 2}},
        {"type": "error", "error": "boom"},
    ]:
        t.event(e)
    t.close()
    text = (tmp_path / "t.txt").read_text()
    assert "USER: hello" in text
    assert "CLAUDE: Hi there" in text
    assert '  -> tool search {"q": "x"}' in text
    assert "NOTICE: approve on Ledger" in text
    assert '  <- search {"n": 2}' in text
    assert "ERROR: boom" in text
