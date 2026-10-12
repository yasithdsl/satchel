import assert from "node:assert/strict";
import { describe, it } from "node:test";
import {
  initialChatState,
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

  it("orders the notice before the Ledger waiting status", () => {
    let state = run([
      {
        type: "tool_call",
        id: "t1",
        name: "request_large_purchase",
        input: { order_id: "o1" },
      },
      { type: "notice", text: "needs your approval on the Ledger" },
    ]);
    const kinds = state.blocks.map((b) => b.kind);
    const noticeIdx = kinds.indexOf("notice");
    const waitIdx = kinds.indexOf("ledger_wait");
    assert.ok(noticeIdx !== -1 && waitIdx !== -1);
    assert.ok(noticeIdx < waitIdx);
    state = run(
      [
        {
          type: "tool_result",
          id: "t1",
          name: "request_large_purchase",
          result: { paid: true, stage: "broadcast" },
        },
      ],
      state,
    );
    assert.equal(state.blocks[state.blocks.length - 1].kind, "order");
  });

  it("shows waiting status for request_budget then resolves it", () => {
    let state = run([
      { type: "tool_call", id: "t1", name: "request_budget", input: {} },
    ]);
    assert.ok(state.blocks.some((b) => b.kind === "ledger_wait"));
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
    assert.ok(!state.blocks.some((b) => b.kind === "ledger_wait"));
    const system = state.blocks.find((b) => b.kind === "system");
    assert.equal(system?.text, "$200 prepaid budget approved");
  });

  it("reports a declined budget", () => {
    const state = run([
      { type: "tool_call", id: "t1", name: "request_budget", input: {} },
      {
        type: "tool_result",
        id: "t1",
        name: "request_budget",
        result: { granted: false, reason: "rejected" },
      },
    ]);
    assert.equal(
      state.blocks.find((b) => b.kind === "system")?.text,
      "Declined on Ledger",
    );
  });

  it("creates an order chip on paid_from_budget", () => {
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
    const chip = state.blocks.find((b) => b.kind === "order");
    assert.ok(chip && chip.kind === "order");
    assert.equal(chip.order.orderId, "o9");
    assert.equal(chip.order.amountUsd, 179);
  });

  it("maps a blocked large purchase to a vault message", () => {
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
    assert.equal(
      state.blocks.find((b) => b.kind === "system")?.text,
      "Payment blocked by your vault",
    );
  });

  it("transient activity lines come and go", () => {
    let state = run([
      { type: "tool_call", id: "t1", name: "search_products", input: {} },
    ]);
    const activity = state.blocks.find((b) => b.kind === "activity");
    assert.equal(activity?.text, "Searching the shop…");
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

  it("sendUserMessage appends a user block and marks busy", () => {
    const state = sendUserMessage(initialChatState, "hi");
    assert.equal(state.blocks[0].kind, "user");
    assert.equal(state.busy, true);
  });

  it("large purchase chip uses the earlier exceeds_budget details", () => {
    const state = run([
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
        result: {
          status: "exceeds_budget",
          order_id: "o5",
          amount_usd: 799,
        },
      },
      {
        type: "tool_call",
        id: "t2",
        name: "request_large_purchase",
        input: { order_id: "o5" },
      },
      {
        type: "tool_result",
        id: "t2",
        name: "request_large_purchase",
        result: { paid: true, stage: "broadcast" },
      },
    ]);
    const chip = state.blocks.find((b) => b.kind === "order");
    assert.ok(chip && chip.kind === "order");
    assert.equal(chip.order.orderId, "o5");
    assert.equal(chip.order.amountUsd, 799);
  });
});
