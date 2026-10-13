import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { pendingApproval, planSummary } from "../lib/ledger.ts";
import type { XrayState } from "../lib/api.ts";
import type { XrayEvent } from "../lib/xray.ts";

const GRANT = "Give shopper-3c483daf envelope #1 (0.002 BTC), expires 13 Oct 10:10 UTC. Nonce 157c097c898dbb12";
const SPEND = "Pay 0.05 BTC to bcrt1q7ccu...hyfk0p for agent top-up, PSBT 1fc57a4f. Nonce 4616d65d8ab646bf";

function ev(seq: number, type: string, payload: Record<string, unknown> = {}, ts = "2026-10-13T09:00:00.000+00:00"): XrayEvent {
  return { seq, id: `e${seq}`, ts, component: "approver", type, message: type, payload };
}

function state(pending: { text: string; nonce: string } | null, ts = "2026-10-13T09:00:01.000+00:00"): XrayState {
  return {
    ts,
    main_funds: null,
    envelopes: null,
    loss_sink: null,
    random_nonce_signer: false,
    compromise_control: null,
    pending_approval: {
      pending: pending ? { kind: "envelope_grant", started_at: ts, ...pending } : null,
    },
    errors: {},
  };
}

describe("plan summary", () => {
  it("reads a budget grant in plain English without IDs", () => {
    const s = planSummary({ kind: "envelope_grant", text: GRANT });
    assert.equal(s.headline, "Give your shopping agent a $200 budget.");
    assert.equal(s.detail, "It can spend it on its own until 10:10 UTC.");
    assert.doesNotMatch(`${s.headline} ${s.detail}`, /shopper-|Nonce|[0-9a-f]{8}/);
  });

  it("reads a main-funds payment with its label, not the address", () => {
    const s = planSummary({ kind: "large_spend", text: SPEND });
    assert.equal(s.headline, "Pay $5,000 from your main funds.");
    assert.equal(s.detail, "Labelled “agent top-up”.");
    assert.doesNotMatch(`${s.headline} ${s.detail}`, /bcrt1|PSBT|Nonce/);
  });
});

describe("pending approval", () => {
  const requested = ev(5, "approval_requested", { kind: "envelope_grant", text: GRANT, nonce: "n1" });

  it("waits for the story to reach the request before taking over", () => {
    assert.equal(pendingApproval([requested], 4, null), null);
    assert.deepEqual(pendingApproval([requested], 5, null), {
      kind: "envelope_grant",
      text: GRANT,
      nonce: "n1",
    });
  });

  it("closes as soon as the request is decided", () => {
    for (const outcome of ["approval_granted", "approval_rejected", "approval_failed"]) {
      assert.equal(pendingApproval([requested, ev(6, outcome)], 5, null), null, outcome);
    }
  });

  it("drops a request the approver no longer has", () => {
    const later = state(null, "2026-10-13T09:00:30.000+00:00");
    assert.equal(pendingApproval([requested], 5, later), null);
  });

  it("shows a pending request from state after a reload with no events", () => {
    assert.deepEqual(pendingApproval([], 0, state({ text: GRANT, nonce: "n2" })), {
      kind: "envelope_grant",
      text: GRANT,
      nonce: "n2",
    });
  });
});
