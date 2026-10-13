import assert from "node:assert/strict";
import { describe, it } from "node:test";
import {
  approvalText,
  initialChatState,
  MAX_CARDS,
  reduce,
  sendUserMessage,
  type ChatState,
} from "../lib/chat.ts";

function run(events: Record<string, unknown>[], state = initialChatState) {
  return events.reduce((s, e) => reduce(s, e as never), state);
}

const PRODUCT = {
  id: "aurora",
  name: "Aurora ANC Wireless Headphones",
  seller: "Aurora Audio",
  category: "headphones",
  price_usd: 179,
  price_btc: "0.00179",
  price_sats: 179_000,
  delivery_date: "2026-10-13",
  available: 12,
};

describe("chat reducer", () => {
  it("captures the session id and streams assistant text", () => {
    const state = run([
      { type: "session", session_id: "s1" },
      { type: "text", delta: "Hello " },
      { type: "text", delta: "there" },
      { type: "done" },
    ]);
    assert.equal(state.sessionId, "s1");
    assert.equal(state.busy, false);
    assert.deepEqual(
      state.blocks.map((b) => b.kind),
      ["assistant"],
    );
    const block = state.blocks[0];
    assert.ok(block.kind === "assistant");
    assert.equal(block.text, "Hello there");
  });

  it("renders suggest_products results as cards", () => {
    const state = run([
      { type: "tool_call", id: "t1", name: "suggest_products", input: {} },
      {
        type: "tool_result",
        id: "t1",
        name: "suggest_products",
        result: { products: [PRODUCT, { id: "bad", error: "no" }] },
      },
    ]);
    const cards = state.blocks.find((b) => b.kind === "cards");
    assert.ok(cards && cards.kind === "cards");
    assert.equal(cards.products.length, 1);
    assert.equal(cards.products[0].name, PRODUCT.name);
  });

  function approvals(state: ChatState) {
    return state.blocks.flatMap((b) => (b.kind === "approval" ? [b] : []));
  }

  it("shows one approval row for a budget request and resolves it", () => {
    let state = run([
      { type: "tool_call", id: "t1", name: "request_budget", input: { amount_usd: 200 } },
    ]);
    assert.equal(approvals(state).length, 1);
    assert.equal(
      approvalText(approvals(state)[0].approval),
      "Needs your approval on Ledger: a $200 budget",
    );
    state = run(
      [
        {
          type: "tool_result",
          id: "t1",
          name: "request_budget",
          result: { granted: true, budget_sats: 200_000, budget_usd: 200 },
        },
      ],
      state,
    );
    assert.equal(approvals(state).length, 1);
    assert.equal(approvals(state)[0].approval.status, "approved");
    assert.equal(
      approvalText(approvals(state)[0].approval),
      "Approved on Ledger: $200 budget",
    );
  });

  it("marks a budget rejected on the Ledger", () => {
    const state = run([
      { type: "tool_call", id: "t1", name: "request_budget", input: { amount_usd: 200 } },
      {
        type: "tool_result",
        id: "t1",
        name: "request_budget",
        result: { granted: false, reason: "Rejected on the Ledger" },
      },
    ]);
    assert.equal(approvals(state)[0].approval.status, "rejected");
  });

  it("a tool error fails the approval row without showing the raw error", () => {
    const state = run([
      { type: "tool_call", id: "t1", name: "request_budget", input: { amount_usd: 200 } },
      {
        type: "tool_result",
        id: "t1",
        name: "request_budget",
        result: { error: "/grants returned 503: approver request failed" },
      },
    ]);
    const row = approvals(state)[0];
    assert.equal(row.approval.status, "failed");
    assert.doesNotMatch(approvalText(row.approval), /503|grants/);
    assert.match(state.lastError ?? "", /503/);
  });

  it("creates an order card on paid_from_budget", () => {
    const state = run([
      {
        type: "tool_call",
        id: "t1",
        name: "buy_product",
        input: { product_id: "aurora" },
      },
      {
        type: "tool_result",
        id: "t1",
        name: "buy_product",
        result: {
          status: "paid_from_budget",
          order_id: "o9",
          product: "Aurora",
          amount_usd: 179,
          delivery_date: "2026-10-13",
        },
      },
    ]);
    const card = state.blocks.find((b) => b.kind === "order");
    assert.ok(card && card.kind === "order");
    assert.equal(card.order.orderId, "o9");
    assert.equal(card.order.amountUsd, 179);
  });

  it("a large purchase is one row that names the item and amount", () => {
    const known = run([
      { type: "tool_call", id: "s1", name: "search_products", input: {} },
      {
        type: "tool_result",
        id: "s1",
        name: "search_products",
        result: {
          results: [
            {
              listing: {
                id: "featherbook-13",
                name: "Featherbook 13",
                category: "laptops",
                delivery_date: "2026-10-16",
              },
            },
          ],
        },
      },
    ]);
    let state = run(
      [
        {
          type: "tool_call",
          id: "b1",
          name: "buy_product",
          input: { product_id: "featherbook-13" },
        },
        {
          type: "tool_result",
          id: "b1",
          name: "buy_product",
          result: { status: "exceeds_budget", order_id: "o5", amount_usd: 799 },
        },
        {
          type: "tool_call",
          id: "t2",
          name: "request_large_purchase",
          input: { order_id: "o5" },
        },
        { type: "notice", text: "needs your approval on the Ledger" },
      ],
      known,
    );
    assert.equal(approvals(state).length, 1);
    assert.equal(
      approvalText(approvals(state)[0].approval),
      "Needs your approval on Ledger: $799 laptop from main funds",
    );
    state = run(
      [
        {
          type: "tool_result",
          id: "t2",
          name: "request_large_purchase",
          result: { paid: true, stage: "broadcast" },
        },
      ],
      state,
    );
    assert.equal(approvals(state)[0].approval.status, "approved");
    const card = state.blocks.find((b) => b.kind === "order");
    assert.ok(card && card.kind === "order");
    assert.equal(card.order.orderId, "o5");
    assert.equal(card.order.name, "Featherbook 13");
    assert.equal(card.order.amountUsd, 799);
  });

  it("a vault block turns the row red, with nothing sent", () => {
    const state = run([
      {
        type: "tool_call",
        id: "t1",
        name: "request_large_purchase",
        input: { order_id: "o1" },
      },
      {
        type: "tool_result",
        id: "t1",
        name: "request_large_purchase",
        result: { paid: false, stage: "verification", reason: "bad sig" },
      },
    ]);
    const row = approvals(state)[0];
    assert.equal(row.approval.status, "blocked");
    assert.match(approvalText(row.approval), /Blocked by your vault.*Nothing was sent/);
  });

  it("transient activity lines come and go", () => {
    let state = run([
      { type: "tool_call", id: "t1", name: "search_products", input: {} },
    ]);
    const activity = state.blocks.find((b) => b.kind === "activity");
    assert.ok(activity && activity.kind === "activity");
    assert.equal(activity.text, "Searching the shop…");
    state = run(
      [
        {
          type: "tool_result",
          id: "t1",
          name: "search_products",
          result: { count: 3, results: [] },
        },
      ],
      state,
    );
    assert.ok(!state.blocks.some((b) => b.kind === "activity"));
  });

  it("shows at most three product cards", () => {
    const products = [1, 2, 3, 4].map((i) => ({ ...PRODUCT, id: `p${i}` }));
    const state = run([
      { type: "tool_call", id: "t1", name: "suggest_products", input: {} },
      { type: "tool_result", id: "t1", name: "suggest_products", result: { products } },
    ]);
    const cards = state.blocks.find((b) => b.kind === "cards");
    assert.ok(cards && cards.kind === "cards");
    assert.equal(cards.products.length, MAX_CARDS);
  });

  it("a stream error becomes a calm retry row for the last message", () => {
    let state = sendUserMessage(initialChatState, "find headphones");
    state = run([{ type: "error", error: "chat failed: 500" }], state);
    const last = state.blocks[state.blocks.length - 1];
    assert.ok(last.kind === "retry");
    assert.equal(last.message, "find headphones");
    assert.equal(state.busy, false);
    state = sendUserMessage(state, "find headphones");
    assert.ok(!state.blocks.some((b) => b.kind === "retry"));
  });

  it("sendUserMessage appends a user block and marks busy", () => {
    const state = sendUserMessage(initialChatState, "hi");
    assert.equal(state.blocks[0].kind, "user");
    assert.equal(state.busy, true);
  });
});
