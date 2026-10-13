import assert from "node:assert/strict";
import { describe, it } from "node:test";
import {
  agentIdForSession,
  attackSeen,
  budgetFor,
  lostToAttacker,
} from "../lib/balances.ts";
import type { XrayState } from "../lib/api.ts";
import type { XrayEvent } from "../lib/xray.ts";

const STATE_TS = "2026-10-13T09:00:10.000+00:00";

function state(envelope: Partial<NonNullable<XrayState["envelopes"]>[number]> | null, sink = 0): XrayState {
  return {
    ts: STATE_TS,
    main_funds: {
      fingerprint: "f",
      addresses: 3,
      utxos: 3,
      balance_sats: 100_000_000,
      available_sats: 100_000_000,
    },
    envelopes: envelope
      ? [
          {
            index: 0,
            budget_sats: 200_000,
            assigned_to: "shopper-1",
            status: "assigned",
            balance_sats: 200_000,
            available_sats: 200_000,
            ...envelope,
          },
        ]
      : [],
    loss_sink: { wallet: "loss-sink", confirmed_sats: 0, pending_sats: sink, last_address: null },
    random_nonce_signer: false,
    compromise_control: { enabled: true },
    pending_approval: { pending: null },
    errors: {},
  };
}

function ev(type: string, payload: Record<string, unknown>, ts = "2026-10-13T09:00:05.000+00:00"): XrayEvent {
  return { seq: 1, id: "e", ts, component: "agent", type, message: type, payload };
}

describe("balances", () => {
  it("finds the agent behind a chat session", () => {
    const events = [ev("tool_call", { session_id: "s1", agent_id: "shopper-1", tool: "x" })];
    assert.equal(agentIdForSession(events, "s1"), "shopper-1");
    assert.equal(agentIdForSession(events, "s2"), null);
    assert.equal(agentIdForSession(events, null), null);
  });

  it("no assigned envelope means no budget", () => {
    assert.equal(budgetFor(state(null), [], "shopper-1"), null);
  });

  it("a fresh budget is all there", () => {
    assert.deepEqual(budgetFor(state({}), [], "shopper-1"), {
      remainingSats: 200_000,
      budgetSats: 200_000,
    });
  });

  it("while a payment confirms, its change is what is left", () => {
    const paid = ev("payment_sent", { envelope_index: 0, amount_sats: 179_000, change_sats: 20_718 });
    // Chain state still shows the spent coin as confirmed but no longer available.
    const view = budgetFor(state({ available_sats: 0 }), [paid], "shopper-1");
    assert.deepEqual(view, { remainingSats: 20_718, budgetSats: 200_000 });
  });

  it("a payment newer than the last state refresh counts straight away", () => {
    const paid = ev(
      "payment_sent",
      { envelope_index: 0, amount_sats: 179_000, change_sats: 20_718 },
      "2026-10-13T09:00:11.000+00:00",
    );
    assert.equal(budgetFor(state({}), [paid], "shopper-1")?.remainingSats, 20_718);
  });

  it("once confirmed, chain state is the truth", () => {
    const paid = ev("payment_sent", { envelope_index: 0, amount_sats: 179_000, change_sats: 20_718 });
    const view = budgetFor(
      state({ balance_sats: 20_718, available_sats: 20_718 }),
      [paid],
      "shopper-1",
    );
    assert.equal(view?.remainingSats, 20_718);
  });

  it("before the state refresh, the wallet event shows the new budget", () => {
    const loaded = ev("wallet_loaded", { envelope_index: 1, budget_sats: 200_000, agent_id: "shopper-2" });
    assert.deepEqual(budgetFor(state({}), [loaded], "shopper-2"), {
      remainingSats: 200_000,
      budgetSats: 200_000,
    });
  });

  it("the loss never double counts a drain the sink already shows", () => {
    const drained = ev("compromise_envelope_drained", { amount_sats: 199_800 });
    assert.equal(lostToAttacker(state({}, 0), [drained]), 199_800);
    assert.equal(lostToAttacker(state({}, 199_800), [drained]), 199_800);
    assert.equal(lostToAttacker(state({}, 0), []), 0);
  });

  it("knows when the attack scene has started", () => {
    assert.equal(attackSeen([]), false);
    assert.equal(attackSeen([ev("compromise_started", {})]), true);
  });
});
