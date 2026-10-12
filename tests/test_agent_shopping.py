"""Done-criterion e2e: a scripted model shops through the full stack."""

import json
import os
import urllib.request
from datetime import date, timedelta
from pathlib import Path

import pytest
from anthropic.types import Message, TextBlock, ToolUseBlock, Usage
from fastapi.testclient import TestClient

from satchel_agent.agent import ShoppingAgent
from satchel_agent.clients import LaptopClient, MarketplaceClient
from satchel_agent.server import create_app as create_agent_app
from satchel_agent.tools import ToolBox
from satchel_laptop.app import create_app as create_laptop_app
from satchel_laptop.approver_client import ApproverClient
from satchel_laptop.funding import fund_envelopes
from satchel_laptop.main_funds import fund_main_funds
from satchel_laptop.signer_client import SignerClient
from satchel_laptop.state import LaptopState
from satchel_laptop.vault_client import VaultClient
from satchel_marketplace.app import create_app as create_marketplace_app
from satchel_marketplace.catalogue import Catalogue
from satchel_marketplace.merchant import MerchantWallet
from satchel_marketplace.store import Store
from satchel_signer.app import create_app as create_signer_app
from satchel_vault.app import create_app as create_vault_app
from satchel_vault.vault import Vault

DICE = "1" * 25
PASSPHRASE = "agent e2e passphrase"


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


def message(*blocks, stop_reason="end_turn"):
    return Message(
        id="msg_scripted",
        type="message",
        role="assistant",
        model="scripted",
        content=list(blocks),
        stop_reason=stop_reason,
        usage=Usage(input_tokens=10, output_tokens=10),
    )


def tool_use(name, tool_input):
    return ToolUseBlock(
        type="tool_use",
        id=f"toolu_{name}",
        name=name,
        input=tool_input,
    )


def _tool_results(messages):
    found = []
    for m in messages:
        if m.get("role") != "user":
            continue
        for block in m.get("content") or []:
            if isinstance(block, dict) and block.get("type") == "tool_result":
                found.append(json.loads(block["content"]))
    return found


class ScriptedModel:
    """Decides each response from the conversation state (no LLM)."""

    def __init__(self, deliver_by: date):
        self.deliver_by = deliver_by.isoformat()
        self.messages = self
        self.calls = []

    def stream(self, **kwargs):
        self.calls.append(kwargs)
        return ScriptedStream(self._decide(kwargs["messages"]))

    def _decide(self, messages) -> Message:
        last = messages[-1]
        tool_results = _tool_results(messages[-1:])
        if tool_results:
            result = tool_results[-1]
            if "results" in result:
                return message(
                    tool_use("request_budget", {"amount_usd": 200}),
                    stop_reason="tool_use",
                )
            if result.get("granted"):
                return message(
                    TextBlock(type="text", text="Budget granted. Options: ...")
                )
            if result.get("status") == "paid_from_budget":
                return message(
                    TextBlock(type="text", text="Bought the Aurora headphones.")
                )
            if "status" in result and "order_id" in result:
                return message(
                    TextBlock(type="text", text="The order is paid.")
                )
            return message(TextBlock(type="text", text="Hmm."))
        text = ""
        for block in last.get("content") or []:
            if isinstance(block, dict) and block.get("type") == "text":
                text = block["text"]
        if text.startswith("Find me"):
            return message(
                tool_use(
                    "search_products",
                    {
                        "query": "headphones",
                        "max_price_usd": 200,
                        "deliver_by": self.deliver_by,
                    },
                ),
                stop_reason="tool_use",
            )
        if text.startswith("Buy"):
            return message(
                tool_use(
                    "buy_product",
                    {"product_id": "aurora-anc-wireless-headphones"},
                ),
                stop_reason="tool_use",
            )
        if text.startswith("Has it been paid"):
            order_id = _tool_results(messages)[-1]["order_id"]
            return message(
                tool_use("check_order", {"order_id": order_id}),
                stop_reason="tool_use",
            )
        return message(TextBlock(type="text", text="What would you like?"))


def parse_sse(body: str) -> list[dict]:
    return [
        json.loads(chunk[6:])
        for chunk in body.split("\n\n")
        if chunk.startswith("data: ")
    ]


def coming_friday() -> date:
    today = date.today()
    days = (4 - today.weekday()) % 7
    return today + timedelta(days=days or 7)


def build_stack(approver, node, tmp_path):
    with urllib.request.urlopen(f"{approver}/address", timeout=30) as r:
        ledger = json.loads(r.read())["address"].lower()
    vault = Vault(tmp_path / "vault")
    vault.setup(DICE, PASSPHRASE, ledger)
    vault.unlock(PASSPHRASE)
    vault.allocate_demo_envelopes()
    vault_client = VaultClient(http=TestClient(create_vault_app(vault)))
    state = LaptopState(tmp_path / "laptop" / "state.json")
    funded = fund_envelopes(vault_client, node, state)
    assert len(funded) == 3

    merchant = MerchantWallet(node)
    merchant.ensure()
    store = Store(Catalogue.load(), merchant, tmp_path / "marketplace")

    laptop_app = create_laptop_app(
        vault_client,
        node,
        state,
        approver=ApproverClient(base_url=approver),
        signer=SignerClient(http=TestClient(create_signer_app())),
        flows_dir=tmp_path / "laptop",
    )
    marketplace = MarketplaceClient(
        http=TestClient(create_marketplace_app(store))
    )
    laptop = LaptopClient(http=TestClient(laptop_app))
    model = ScriptedModel(coming_friday())

    def toolbox_factory(session_id, agent_id):
        return ToolBox(
            marketplace,
            laptop,
            node,
            agent_id,
            session_id=session_id,
            demo_auto="approve",
        )

    agent = ShoppingAgent(model, toolbox_factory)
    sessions = {}
    return TestClient(create_agent_app(agent, sessions)), store, vault


def post_chat(client, message, session_id=None):
    body = {"message": message}
    if session_id:
        body["session_id"] = session_id
    events = parse_sse(client.post("/chat", json=body).text)
    return events[0]["session_id"], events[1:]


def chat_transcript(client, user_text, session_id, transcript):
    sid, events = post_chat(client, user_text, session_id)
    lines = [f"USER: {user_text}"]
    pending_text = []
    for event in events:
        kind = event.get("type")
        if kind == "text":
            pending_text.append(event["delta"])
            continue
        if pending_text:
            lines.append("CLAUDE: " + "".join(pending_text))
            pending_text = []
        if kind == "notice":
            lines.append(f"NOTICE: {event['text']}")
        elif kind == "tool_call":
            lines.append(
                f"  -> tool {event['name']} {json.dumps(event['input'])}"
            )
        elif kind == "tool_result":
            lines.append(
                f"  <- {event['name']} "
                f"{json.dumps(event['result'])[:600]}"
            )
        elif kind == "error":
            lines.append(f"  !! error {event['error']}")
    if pending_text:
        lines.append("CLAUDE: " + "".join(pending_text))
    for line in lines:
        print(line)
    transcript.extend(lines)
    return sid, events


def save_transcript(test_name, transcript):
    path = Path(f"/tmp/satchel-live-{test_name}.txt")
    path.write_text("\n".join(transcript) + "\n")
    return path


def tool_events(events, name):
    return [
        e["result"]
        for e in events
        if e.get("type") == "tool_result" and e.get("name") == name
    ]


@pytest.mark.speculos
@pytest.mark.regtest
def test_agent_shopping_end_to_end(approver, node, tmp_path):
    client, _store, _vault = build_stack(approver, node, tmp_path)

    sid, events = post_chat(
        client, "Find me headphones under $200 that arrive by Friday."
    )
    search_calls = [
        e
        for e in events
        if e.get("type") == "tool_call" and e["name"] == "search_products"
    ]
    assert search_calls[0]["input"]["max_price_usd"] == 200
    assert search_calls[0]["input"]["deliver_by"] == coming_friday().isoformat()
    search_results = tool_events(events, "search_products")
    assert search_results[0]["count"] >= 3
    budget_results = tool_events(events, "request_budget")
    assert budget_results[0]["granted"] is True
    assert budget_results[0]["budget_sats"] == 200_000
    assert budget_results[0]["envelope_index"] == 1
    assert events[-1] == {"type": "done"}

    sid, events = post_chat(client, "Buy the Aurora ones.", sid)
    buy_results = tool_events(events, "buy_product")
    assert buy_results[0]["status"] == "paid_from_budget"
    assert buy_results[0]["amount_sats"] == 179_000
    assert buy_results[0]["txid"]
    remaining = buy_results[0]["remaining_sats"]
    fee = 200_000 - 179_000 - remaining
    assert fee > 0
    assert remaining >= 0
    node.mine_blocks(1, node.faucet_address())

    sid, events = post_chat(client, "Has it been paid?", sid)
    order_results = tool_events(events, "check_order")
    assert order_results[0]["status"] == "paid"
    assert buy_results[0]["txid"] in order_results[0]["txids"]

    events_log = Path(os.environ["SATCHEL_EVENT_LOG"]).read_text()
    for name in (
        "search_products",
        "request_budget",
        "buy_product",
        "check_order",
    ):
        assert f'"tool_call"' in events_log
        assert f'"{name}"' in events_log
    flow_dir = tmp_path / "laptop" / "flows"
    flows = list(flow_dir.glob("*.json"))
    assert flows
    released_wifs = {
        _vault._master.envelope(i).wif for i in range(2)
    }
    for path in flows:
        text = path.read_text()
        for wif in released_wifs:
            assert wif not in text
        assert '"wif"' not in text or '"wif": "<redacted>"' in text


def build_live_stack(approver, node, tmp_path, main_funds=False):
    import anthropic

    with urllib.request.urlopen(f"{approver}/address", timeout=30) as r:
        ledger = json.loads(r.read())["address"].lower()
    vault = Vault(tmp_path / "vault")
    vault.setup(DICE, PASSPHRASE, ledger)
    vault.unlock(PASSPHRASE)
    vault.allocate_demo_envelopes()
    vault_client = VaultClient(http=TestClient(create_vault_app(vault)))
    state = LaptopState(tmp_path / "laptop" / "state.json")
    fund_envelopes(vault_client, node, state)
    if main_funds:
        fund_main_funds(vault_client, node, state)
    merchant = MerchantWallet(node)
    merchant.ensure()
    store = Store(Catalogue.load(), merchant, tmp_path / "marketplace")
    laptop_app = create_laptop_app(
        vault_client,
        node,
        state,
        approver=ApproverClient(base_url=approver),
        signer=SignerClient(http=TestClient(create_signer_app())),
        flows_dir=tmp_path / "laptop",
    )
    marketplace = MarketplaceClient(
        http=TestClient(create_marketplace_app(store))
    )
    laptop = LaptopClient(http=TestClient(laptop_app))

    def toolbox_factory(session_id, agent_id):
        return ToolBox(
            marketplace,
            laptop,
            node,
            agent_id,
            session_id=session_id,
            demo_auto="approve",
        )

    agent = ShoppingAgent(anthropic.Anthropic(), toolbox_factory)
    sessions = {}
    client = TestClient(create_agent_app(agent, sessions))
    return client, store


@pytest.mark.live_llm
@pytest.mark.speculos
@pytest.mark.regtest
@pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"), reason="ANTHROPIC_API_KEY not set"
)
def test_agent_shopping_live_llm(approver, node, tmp_path):
    client, store = build_live_stack(approver, node, tmp_path)
    transcript = []
    sid, events1 = chat_transcript(
        client,
        "Find me headphones under $200 that arrive by Friday.",
        None,
        transcript,
    )
    _, events2 = chat_transcript(
        client, "Buy the Aurora ANC ones, cheapest option.", sid, transcript
    )
    save_transcript("test_agent_shopping_live_llm", transcript)
    search_calls = [
        e
        for e in events1
        if e.get("type") == "tool_call" and e["name"] == "search_products"
    ]
    assert any(
        c["input"].get("deliver_by") == coming_friday().isoformat()
        for c in search_calls
    ), "no search_products call used the coming Friday as deliver_by"
    budgets = [
        e["result"]
        for e in events1 + events2
        if e.get("type") == "tool_result" and e["name"] == "request_budget"
    ]
    assert budgets and budgets[-1]["granted"] is True
    assert budgets[-1]["budget_sats"] == 200_000
    assert budgets[-1]["envelope_index"] == 1
    buys = [
        e["result"]
        for e in events2
        if e.get("type") == "tool_result" and e["name"] == "buy_product"
    ]
    paid = [r for r in buys if r.get("status") == "paid_from_budget"]
    assert paid, "the live model did not buy from the envelope"
    assert paid[-1]["amount_sats"] == 179_000
    fee = 200_000 - paid[-1]["amount_sats"] - paid[-1]["remaining_sats"]
    assert fee > 0
    assert paid[-1]["remaining_sats"] >= 0
    order_ids = [
        e["result"]["order_id"]
        for e in events2
        if e.get("type") == "tool_result"
        and e.get("result", {}).get("order_id")
    ]
    assert order_ids, "the live model did not place an order"
    node.mine_blocks(1, node.faucet_address())
    final = store.status(order_ids[-1])
    assert final["status"] == "paid"


@pytest.mark.live_llm
@pytest.mark.speculos
@pytest.mark.regtest
@pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"), reason="ANTHROPIC_API_KEY not set"
)
def test_agent_large_purchase_live_llm(approver, node, tmp_path):
    client, store = build_live_stack(
        approver, node, tmp_path, main_funds=True
    )
    transcript = []
    sid, events1 = chat_transcript(
        client,
        "Please get a prepaid budget of $200 for today's shopping.",
        None,
        transcript,
    )
    sid, events2 = chat_transcript(
        client, "Buy me the Featherbook 13 laptop.", sid, transcript
    )
    events = events1 + events2
    if not any(
        e.get("type") == "tool_call" and e["name"] == "request_large_purchase"
        for e in events2
    ):
        _, events3 = chat_transcript(
            client, "Yes, go ahead.", sid, transcript
        )
        events += events3
    save_transcript("test_agent_large_purchase_live_llm", transcript)

    budgets = [
        e["result"]
        for e in events
        if e.get("type") == "tool_result" and e["name"] == "request_budget"
    ]
    assert budgets and budgets[-1]["granted"] is True
    assert budgets[-1]["budget_sats"] == 200_000

    buy_calls = [
        e
        for e in events
        if e.get("type") == "tool_call" and e["name"] == "buy_product"
    ]
    assert any(
        c["input"].get("product_id") == "featherbook-13" for c in buy_calls
    )
    buy_results = [
        e["result"]
        for e in events
        if e.get("type") == "tool_result" and e["name"] == "buy_product"
    ]
    exceeded = [r for r in buy_results if r.get("status") == "exceeds_budget"]
    assert exceeded, "the envelope should not cover a $799 laptop"
    order_ids = [r["order_id"] for r in exceeded if r.get("order_id")]
    assert order_ids

    large = [
        e["result"]
        for e in events
        if e.get("type") == "tool_result"
        and e["name"] == "request_large_purchase"
    ]
    assert large and large[-1].get("paid") is True

    call_idx = next(
        i
        for i, e in enumerate(events)
        if e.get("type") == "tool_call"
        and e["name"] == "request_large_purchase"
    )
    notice = events[call_idx + 1]
    assert notice == {
        "type": "notice",
        "text": "This purchase exceeds your prepaid budget and needs your approval on the Ledger",
    }
    assert events[call_idx + 2]["type"] == "tool_result"
    assert events[call_idx + 2]["name"] == "request_large_purchase"

    log = Path(os.environ["SATCHEL_EVENT_LOG"]).read_text().splitlines()
    notice_line = next(
        i
        for i, line in enumerate(log)
        if '"large_purchase_notice"' in line
    )
    spend_plan_line = next(
        i
        for i, line in enumerate(log)
        if '"plan_sent_to_approver"' in line
        and json.loads(line)["payload"].get("flow") == "spend"
    )
    assert notice_line < spend_plan_line

    node.mine_blocks(1, node.faucet_address())
    final = store.status(order_ids[-1])
    assert final["status"] == "paid"
