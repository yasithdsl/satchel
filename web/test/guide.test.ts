import assert from "node:assert/strict";
import { describe, it } from "node:test";
import {
  advance,
  currentStep,
  SCENARIOS,
  startScenario,
} from "../lib/guide.ts";
import type { XrayEvent } from "../lib/xray.ts";

function ev(
  seq: number,
  component: string,
  type: string,
  payload: Record<string, unknown> | null = null,
): XrayEvent {
  return {
    seq,
    id: `id-${seq}`,
    ts: "2026-10-12T20:00:00.000+00:00",
    component,
    type,
    message: `m ${type}`,
    payload,
  };
}

describe("demo guide", () => {
  it("scenario 1 completes through its event chain", () => {
    let p = startScenario("purchase", 10);
    assert.equal(currentStep(p)?.id, "ask");
    p = advance(
      p,
      ev(11, "agent", "tool_call", {
        tool: "request_budget",
        input: { amount_usd: 200 },
      }),
    );
    assert.equal(currentStep(p)?.id, "approve-budget");
    p = advance(
      p,
      ev(12, "vault", "envelope_released", { envelope_index: 1 }),
    );
    assert.equal(currentStep(p)?.id, "buy");
    p = advance(
      p,
      ev(13, "agent", "payment_sent", { amount_sats: 179_000 }),
    );
    assert.equal(currentStep(p)?.id, "mine");
    p = advance(p, ev(14, "network", "block_mined"));
    assert.equal(currentStep(p)?.id, "mine");
    p = advance(
      p,
      ev(15, "marketplace", "order_paid", { order_id: "o" }),
    );
    assert.equal(p.done, true);
  });

  it("ignores events that arrived before the step became current", () => {
    let p = startScenario("purchase", 0);
    p = advance(
      p,
      ev(1, "agent", "tool_call", {
        tool: "request_budget",
        input: {},
      }),
    );
    p = advance(
      p,
      ev(2, "vault", "envelope_released", { envelope_index: 1 }),
    );
    assert.equal(currentStep(p)?.id, "buy");
    const stale = ev(2, "agent", "payment_sent", {});
    assert.equal(stale.seq, 2);
    p = advance(p, stale);
    assert.equal(currentStep(p)?.id, "buy");
    p = advance(p, ev(3, "agent", "payment_sent", {}));
    assert.equal(currentStep(p)?.id, "mine");
  });

  it("steps armed at activation ignore older events", () => {
    let p = startScenario("purchase", 50);
    p = advance(
      p,
      ev(49, "agent", "tool_call", { tool: "request_budget" }),
    );
    assert.equal(currentStep(p)?.id, "ask");
    p = advance(
      p,
      ev(51, "agent", "tool_call", { tool: "request_budget" }),
    );
    assert.equal(currentStep(p)?.id, "approve-budget");
  });

  it("scenario 2 walks the compromise chain and auto-completes the result", () => {
    let p = startScenario("compromise", 0);
    p = advance(p, ev(1, "network", "block_mined"));
    assert.equal(currentStep(p)?.id, "compromise");
    p = advance(
      p,
      ev(2, "agent", "compromise_envelope_drained", {}),
    );
    assert.equal(currentStep(p)?.id, "reject");
    p = advance(
      p,
      ev(3, "agent", "compromise_large_spend_blocked", {}),
    );
    assert.equal(p.done, true);
  });

  it("scenario 3 walks the malicious-signer chain", () => {
    let p = startScenario("malicious-signer", 0);
    p = advance(p, ev(1, "signer", "random_nonce_enabled"));
    assert.equal(currentStep(p)?.id, "ask-laptop");
    p = advance(p, ev(2, "agent", "large_purchase_notice"));
    assert.equal(currentStep(p)?.id, "approve-spend");
    p = advance(p, ev(3, "vault", "spend_keys_released"));
    assert.equal(currentStep(p)?.id, "blocked");
    p = advance(p, ev(4, "vault", "verification_failed"));
    assert.equal(currentStep(p)?.id, "random-off");
    p = advance(p, ev(5, "signer", "random_nonce_disabled"));
    assert.equal(p.done, true);
  });

  it("payment_sent to the loss sink does not complete the buy step", () => {
    let p = startScenario("purchase", 0);
    p = advance(
      p,
      ev(1, "agent", "tool_call", { tool: "request_budget" }),
    );
    p = advance(p, ev(2, "vault", "envelope_released", {}));
    p = advance(
      p,
      ev(
        3,
        "agent",
        "payment_sent",
        { amount_sats: 5_000 },
      ),
    );
    assert.equal(currentStep(p)?.id, "mine");
  });

  it("every step has text and the scenarios keep their order", () => {
    assert.equal(SCENARIOS.length, 3);
    for (const scenario of SCENARIOS) {
      assert.ok(scenario.steps.length >= 4);
      for (const step of scenario.steps) {
        assert.ok(step.text.length > 0);
      }
    }
  });
});
