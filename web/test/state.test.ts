import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { mergeState } from "../lib/state.ts";
import type { XrayState } from "../lib/api.ts";

function state(patch: Partial<XrayState> = {}): XrayState {
  return {
    ts: "t",
    main_funds: {
      fingerprint: "f",
      addresses: 1,
      utxos: 1,
      balance_sats: 100,
      available_sats: 90,
    },
    envelopes: [
      {
        index: 0,
        budget_sats: 100,
        assigned_to: null,
        status: "unassigned",
        balance_sats: 50,
        available_sats: 50,
      },
    ],
    loss_sink: null,
    random_nonce_signer: false,
    compromise_control: { enabled: true },
    pending_approval: { pending: null },
    errors: {},
    ...patch,
  };
}

describe("mergeState", () => {
  it("returns the first snapshot as-is", () => {
    const s = state();
    assert.equal(mergeState(null, s), s);
  });

  it("keeps the last good field when its source errors", () => {
    const prev = state();
    const next = state({
      main_funds: null,
      envelopes: null,
      errors: {
        main_funds: "GET /main-funds returned 500",
        envelopes: "GET /envelopes returned 500",
      },
    });
    const merged = mergeState(prev, next);
    assert.equal(merged.main_funds, prev.main_funds);
    assert.equal(merged.envelopes, prev.envelopes);
    assert.equal(merged.errors, next.errors);
  });

  it("uses the new value when the source recovered", () => {
    const prev = state({ main_funds: null });
    const next = state();
    assert.equal(mergeState(prev, next).main_funds, next.main_funds);
  });

  it("does not resurrect a field that is null without an error", () => {
    const prev = state({ loss_sink: { wallet: "w", confirmed_sats: 1, pending_sats: 0, last_address: null } });
    const next = state({ loss_sink: null });
    assert.equal(mergeState(prev, next).loss_sink, null);
  });
});
