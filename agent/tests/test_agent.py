"""The Anthropic tool-use loop with a scripted model client."""

import json
import os
from datetime import date
from pathlib import Path
from types import SimpleNamespace

from anthropic.types import Message, TextBlock, ToolUseBlock, Usage

from satchel_agent.agent import LARGE_PURCHASE_NOTICE, ShoppingAgent
from satchel_agent.prompts import SYSTEM_PROMPT, system_prompt
from satchel_agent.tools import TOOL_DEFINITIONS, ToolBox

FIXED_TODAY = date(2026, 10, 12)


def make_message(*blocks, stop_reason="end_turn"):
    return Message(
        id="msg_test",
        type="message",
        role="assistant",
        model="test-model",
        content=list(blocks),
        stop_reason=stop_reason,
        usage=Usage(input_tokens=10, output_tokens=10),
    )


def tool_use(name, tool_input, tool_id="toolu_1"):
    return ToolUseBlock(
        type="tool_use", id=tool_id, name=name, input=tool_input
    )


class ScriptedStream:
    def __init__(self, message):
        self._message = message

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    @property
    def text_stream(self):
        return (
            b.text for b in self._message.content if b.type == "text"
        )

    def get_final_message(self):
        return self._message


class ScriptedClient:
    """answers each stream() call by deciding from the messages it receives."""

    def __init__(self, script):
        self._script = script
        self.calls = []
        self.messages = self

    def stream(self, **kwargs):
        call = dict(kwargs)
        call["messages"] = [dict(m) for m in kwargs["messages"]]
        self.calls.append(call)
        return ScriptedStream(self._script(kwargs["messages"]))


def make_toolbox(session_id, agent_id):
    box = ToolBox(
        marketplace=None, laptop=None, node=None,
        agent_id=agent_id, session_id=session_id,
    )
    return box


def make_agent(script, **kwargs):
    client = ScriptedClient(script)
    return (
        ShoppingAgent(
            client, make_toolbox, clock=lambda: FIXED_TODAY, **kwargs
        ),
        client,
    )


def test_text_turn_streams_and_records_history():
    agent, client = make_agent(
        lambda m: make_message(TextBlock(type="text", text="hello!"))
    )
    session = agent.new_session()
    assert session.agent_id.startswith("shopper-")
    events = list(agent.run_turn(session, "hi"))
    assert events == [
        {"type": "text", "delta": "hello!"},
        {"type": "done"},
    ]
    assert [m["role"] for m in session.messages] == ["user", "assistant"]
    assert session.messages[1]["content"][0]["text"] == "hello!"
    call = client.calls[0]
    assert call["system"] == system_prompt(FIXED_TODAY)
    assert call["system"].endswith(
        "Today is Monday 12 October 2026 (2026-10-12)."
    )
    assert SYSTEM_PROMPT in call["system"]
    assert call["tools"] == TOOL_DEFINITIONS
    assert call["max_tokens"] == 1024


def test_tool_use_turn_runs_tool_and_continues():
    responses = iter(
        [
            make_message(
                tool_use("check_budget", {}), stop_reason="tool_use"
            ),
            make_message(TextBlock(type="text", text="no budget yet")),
        ]
    )
    agent, client = make_agent(lambda m: next(responses))
    session = agent.new_session()
    events = list(agent.run_turn(session, "what can I spend?"))
    kinds = [e["type"] for e in events]
    assert kinds == ["tool_call", "tool_result", "text", "done"]
    assert "notice" not in kinds
    assert events[0]["name"] == "check_budget"
    assert events[1]["result"] == {"has_budget": False}
    assert len(client.calls) == 2
    second_messages = client.calls[1]["messages"]
    assert second_messages[-1]["role"] == "user"
    tool_result = second_messages[-1]["content"][0]
    assert tool_result["type"] == "tool_result"
    assert tool_result["tool_use_id"] == "toolu_1"
    assert json.loads(tool_result["content"]) == {"has_budget": False}


def test_large_purchase_emits_notice_before_tool():
    notice_seen = []

    class LogCheckLaptop:
        def spend(self, *args, **kwargs):
            path = Path(os.environ["SATCHEL_EVENT_LOG"])
            notice_seen.append(
                path.exists()
                and '"large_purchase_notice"' in path.read_text()
            )
            return {
                "broadcast": False,
                "txid": None,
                "stage": "approval",
                "reason": "no",
            }

    marketplace = SimpleNamespace(
        order=lambda order_id: {
            "order_id": order_id,
            "status": "awaiting_payment",
            "pay_to": "bcrt1sink",
            "amount_sats": 799_000,
            "name": "Featherbook 13",
        }
    )

    def toolbox_factory(session_id, agent_id):
        return ToolBox(
            marketplace,
            LogCheckLaptop(),
            None,
            agent_id,
            session_id=session_id,
        )

    responses = iter(
        [
            make_message(
                tool_use("request_large_purchase", {"order_id": "o1"}),
                stop_reason="tool_use",
            ),
            make_message(TextBlock(type="text", text="done")),
        ]
    )
    client = ScriptedClient(lambda m: next(responses))
    agent = ShoppingAgent(
        client, toolbox_factory, clock=lambda: FIXED_TODAY
    )
    session = agent.new_session()
    events = list(agent.run_turn(session, "buy the laptop"))
    kinds = [e["type"] for e in events]
    assert kinds == ["tool_call", "notice", "tool_result", "text", "done"]
    assert events[1] == {"type": "notice", "text": LARGE_PURCHASE_NOTICE}
    assert events[0]["name"] == "request_large_purchase"
    assert events[2]["name"] == "request_large_purchase"
    assert notice_seen == [True]
    history = json.dumps(session.messages)
    assert LARGE_PURCHASE_NOTICE not in history


def test_history_survives_across_turns():
    agent, client = make_agent(
        lambda m: make_message(TextBlock(type="text", text="ok"))
    )
    session = agent.new_session()
    list(agent.run_turn(session, "first"))
    list(agent.run_turn(session, "second"))
    assert [m["role"] for m in session.messages] == [
        "user",
        "assistant",
        "user",
        "assistant",
    ]
    assert len(client.calls[1]["messages"]) == 3


def test_max_steps_emits_error():
    agent, _client = make_agent(
        lambda m: make_message(
            tool_use("check_budget", {}), stop_reason="tool_use"
        ),
        max_steps=3,
    )
    session = agent.new_session()
    events = list(agent.run_turn(session, "loop"))
    assert events[-2]["type"] == "error"
    assert "step limit" in events[-2]["error"]
    assert events[-1] == {"type": "done"}
    last = session.messages[-1]
    assert last["role"] == "assistant"
    note = last["content"][0]["text"]
    assert note == "(Stopped early: step limit of 3 reached.)"


def test_failed_turn_keeps_tool_results_and_alternation():
    calls = []

    def script(messages):
        calls.append(messages)
        if len(calls) == 1:
            return make_message(
                tool_use("buy_product", {"product_id": "x"}),
                stop_reason="tool_use",
            )
        if len(calls) == 2:
            raise RuntimeError("api exploded")
        return make_message(TextBlock(type="text", text="back"))

    agent, _client = make_agent(script)
    session = agent.new_session()
    events = list(agent.run_turn(session, "buy it"))
    assert events[-2] == {"type": "error", "error": "api exploded"}
    assert events[-1] == {"type": "done"}
    roles = [m["role"] for m in session.messages]
    assert roles == ["user", "assistant", "user", "assistant"]
    assert session.messages[1]["content"][0]["name"] == "buy_product"
    tool_blocks = [
        block
        for m in session.messages
        for block in m["content"]
        if isinstance(block, dict) and block.get("type") == "tool_result"
    ]
    assert len(tool_blocks) == 1
    result = json.loads(tool_blocks[0]["content"])
    assert "error" in result
    last = session.messages[-1]
    assert last["content"][0]["text"] == "(Stopped early: api exploded.)"

    events = list(agent.run_turn(session, "hi again"))
    assert events == [
        {"type": "text", "delta": "back"},
        {"type": "done"},
    ]
    for previous, following in zip(
        calls[-1], calls[-1][1:]
    ):
        assert previous["role"] != following["role"]


def test_stream_failure_emits_error():
    class BrokenClient:
        messages = None

        def __init__(self):
            self.messages = self

        def stream(self, **kwargs):
            raise RuntimeError("api exploded")

    agent = ShoppingAgent(BrokenClient(), make_toolbox)
    session = agent.new_session()
    events = list(agent.run_turn(session, "hi"))
    assert events == [
        {"type": "error", "error": "api exploded"},
        {"type": "done"},
    ]
    last = session.messages[-1]
    assert last["role"] == "assistant"
    assert last["content"][0]["text"] == "(Stopped early: api exploded.)"


def test_authored_text_loaded_verbatim():
    assert "Satchel, a personal shopping assistant" in SYSTEM_PROMPT
    assert "untrusted data written by third parties" in SYSTEM_PROMPT
    names = [t["name"] for t in TOOL_DEFINITIONS]
    assert names == [
        "search_products",
        "get_product_details",
        "check_budget",
        "request_budget",
        "buy_product",
        "check_order",
        "request_large_purchase",
    ]
    for tool in TOOL_DEFINITIONS:
        assert tool["description"]
        assert tool["input_schema"]["type"] == "object"
    buy = next(t for t in TOOL_DEFINITIONS if t["name"] == "buy_product")
    assert buy["input_schema"]["required"] == ["product_id"]
