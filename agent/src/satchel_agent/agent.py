"""The shopping agent: an Anthropic tool-use loop over the ToolBox."""

import json
import os
import threading
import uuid
from dataclasses import dataclass, field
from datetime import date
from typing import Iterator

from satchel_core.events import emit

from .prompts import system_prompt
from .tools import TOOL_DEFINITIONS, ToolBox

DEFAULT_MODEL = "claude-sonnet-5-5"
LARGE_PURCHASE_NOTICE = "This purchase exceeds your prepaid budget and needs your approval on the Ledger"


@dataclass
class Session:
    session_id: str
    agent_id: str
    toolbox: ToolBox
    messages: list = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)


class ShoppingAgent:
    def __init__(
        self,
        client,
        toolbox_factory,
        model: str | None = None,
        max_tokens: int = 1024,
        max_steps: int = 10,
        clock=date.today,
    ):
        self.client = client
        self.toolbox_factory = toolbox_factory
        self.model = (
            model or os.environ.get("SATCHEL_AGENT_MODEL") or DEFAULT_MODEL
        )
        self.max_tokens = max_tokens
        self.max_steps = max_steps
        self.clock = clock

    def new_session(self) -> Session:
        session_id = uuid.uuid4().hex
        agent_id = f"shopper-{session_id[:8]}"
        return Session(
            session_id,
            agent_id,
            self.toolbox_factory(session_id, agent_id),
        )

    def run_turn(self, session: Session, user_text: str) -> Iterator[dict]:
        session.messages.append(
            {
                "role": "user",
                "content": [{"type": "text", "text": user_text}],
            }
        )
        halted = None
        try:
            for _step in range(self.max_steps):
                with self.client.messages.stream(
                    model=self.model,
                    max_tokens=self.max_tokens,
                    system=system_prompt(self.clock()),
                    tools=TOOL_DEFINITIONS,
                    messages=session.messages,
                ) as stream:
                    for delta in stream.text_stream:
                        yield {"type": "text", "delta": delta}
                    final = stream.get_final_message()
                session.messages.append(
                    {
                        "role": "assistant",
                        "content": [
                            block.model_dump(exclude_none=True)
                            for block in final.content
                        ],
                    }
                )
                if final.stop_reason != "tool_use":
                    break
                results = []
                for block in final.content:
                    if block.type != "tool_use":
                        continue
                    yield {
                        "type": "tool_call",
                        "id": block.id,
                        "name": block.name,
                        "input": block.input,
                    }
                    if block.name == "request_large_purchase":
                        yield {
                            "type": "notice",
                            "text": LARGE_PURCHASE_NOTICE,
                        }
                        emit(
                            "agent",
                            "large_purchase_notice",
                            LARGE_PURCHASE_NOTICE,
                            {
                                "session_id": session.session_id,
                                "agent_id": session.agent_id,
                                "tool_use_id": block.id,
                            },
                        )
                    result = session.toolbox.run(block.name, block.input)
                    yield {
                        "type": "tool_result",
                        "id": block.id,
                        "name": block.name,
                        "result": result,
                    }
                    results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": json.dumps(result),
                        }
                    )
                if not results:
                    break
                session.messages.append({"role": "user", "content": results})
            else:
                halted = f"step limit of {self.max_steps} reached"
                yield {"type": "error", "error": halted}
        except Exception as exc:
            halted = str(exc)
            yield {"type": "error", "error": halted}
        if halted is not None and session.messages[-1]["role"] == "user":
            session.messages.append(
                {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "text",
                            "text": f"(Stopped early: {halted}.)",
                        }
                    ],
                }
            )
        yield {"type": "done"}
