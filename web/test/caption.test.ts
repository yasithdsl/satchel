import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { describe, it } from "node:test";
import {
  captionAll,
  captionFor,
  newContext,
  isSilent,
  observe,
  type StoryContext,
} from "../lib/caption.ts";
import type { XrayEvent } from "../lib/xray.ts";

const FIXTURE = JSON.parse(
  readFileSync(new URL("./fixtures/demo-events.json", import.meta.url), "utf8"),
) as XrayEvent[];

let seq = 0;
function ev(
  component: string,
  type: string,
  payload: Record<string, unknown> | null = null,
): XrayEvent {
  return {
    seq: ++seq,
    id: `e${seq}`,
    ts: "2026-10-13T09:00:00.000+00:00",
    component,
    type,
    message: `${component} ${type}`,
    payload,
  };
}

function text(events: XrayEvent[]): string[] {
  return captionAll(events).items.map((i) => i.caption.text);
}

/** Every event type the backend emits, with a representative payload. */
const KNOWN: XrayEvent[] = [
  ev("agent", "tool_call", { tool: "search_products", input: { query: "headphones" } }),
  ev("agent", "tool_call", { tool: "get_product_details", input: {} }),
  ev("agent", "tool_call", { tool: "suggest_products", input: { product_ids: ["a", "b"] } }),
  ev("agent", "tool_call", { tool: "request_budget", input: { amount_usd: 200 } }),
  ev("agent", "tool_call", { tool: "buy_product", input: {} }),
  ev("agent", "tool_call", { tool: "check_budget", input: {} }),
  ev("agent", "tool_call", { tool: "check_order", input: {} }),
  ev("agent", "tool_call", { tool: "request_large_purchase", input: {} }),
  ev("agent", "tool_result", { tool: "buy_product", ok: true }),
  ev("agent", "wallet_loaded", { envelope_index: 0, budget_sats: 200_000, agent_id: "a" }),
  ev("agent", "payment_sent", { envelope_index: 0, amount_sats: 179_000, change_sats: 20_718 }),
  ev("agent", "payment_rejected", { reason: "x" }),
  ev("agent", "payment_failed", {}),
  ev("agent", "large_purchase_notice", {}),
  ev("agent", "compromise_started", { agent_id: "a" }),
  ev("agent", "compromise_envelope_drained", { amount_sats: 199_800 }),
  ev("agent", "compromise_envelope_empty", {}),
  ev("agent", "compromise_large_spend_requested", { amount_sats: 5_000_000 }),
  ev("agent", "compromise_large_spend_blocked", { stage: "approval" }),
  ev("agent", "compromise_large_spend_approved", {}),
  ev("agent", "compromise_finished", {}),
  ev("approver", "demo_automation_enabled"),
  ev("approver", "demo_action"),
  ev("approver", "approval_requested", { kind: "envelope_grant", text: "Give x envelope #0 (0.002 BTC), expires 13 Oct 10:10 UTC. Nonce 1" }),
  ev("approver", "approval_granted", {}),
  ev("approver", "approval_rejected", {}),
  ev("approver", "approval_failed", {}),
  ev("laptop", "envelopes_fetched", { flow_id: "f" }),
  ev("laptop", "plan_sent_to_approver", { flow_id: "f" }),
  ev("laptop", "approval_received", { flow_id: "f" }),
  ev("laptop", "approval_rejected", { flow_id: "f" }),
  ev("laptop", "approval_sent_to_vault", { flow_id: "f" }),
  ev("laptop", "key_release_received", { flow_id: "f" }),
  ev("laptop", "key_delivered_to_agent", { flow_id: "f" }),
  ev("laptop", "change_address_exported", { flow_id: "f" }),
  ev("laptop", "utxos_selected", { flow_id: "f" }),
  ev("laptop", "psbt_built", { flow_id: "f" }),
  ev("laptop", "keys_released", { flow_id: "f" }),
  ev("laptop", "keys_sent_to_signer", { flow_id: "f" }),
  ev("laptop", "signed_tx_received", { flow_id: "f" }),
  ev("laptop", "verification_received", { flow_id: "f" }),
  ev("laptop", "broadcast", { flow_id: "f" }),
  ev("laptop", "receive_addresses_exported", { flow_id: "f" }),
  ev("laptop", "main_funds_funded", { flow_id: "f" }),
  ev("laptop", "envelope_funded", {}),
  ev("laptop", "main_fund_funded", {}),
  ev("laptop", "grant_completed", {}),
  ev("laptop", "grant_failed", {}),
  ev("laptop", "spend_completed", {}),
  ev("laptop", "spend_failed", {}),
  ev("laptop", "setup_completed", {}),
  ev("vault", "seed_created"),
  ev("vault", "vault_unlocked"),
  ev("vault", "unlock_failed"),
  ev("vault", "vault_reset"),
  ev("vault", "envelopes_allocated"),
  ev("vault", "envelopes_exported"),
  ev("vault", "addresses_exported"),
  ev("vault", "release_requested"),
  ev("vault", "envelope_released", { envelope_index: 0 }),
  ev("vault", "release_refused", { reason: "bad signature" }),
  ev("vault", "spend_keys_released", {}),
  ev("vault", "verification_passed", {}),
  ev("vault", "verification_failed", { reasons: ["mismatch"] }),
  ev("signer", "psbt_signed", { nonce: "rfc6979" }),
  ev("signer", "random_nonce_signing", {}),
  ev("signer", "random_nonce_enabled", {}),
  ev("signer", "random_nonce_disabled", {}),
  ev("signer", "sign_refused", {}),
  ev("marketplace", "search", {}),
  ev("marketplace", "order_created", {}),
  ev("marketplace", "payment_seen", {}),
  ev("marketplace", "order_paid", {}),
  ev("network", "block_mined", {}),
];

describe("captions", () => {
  it("every known event type is either captioned or deliberately silent", () => {
    for (const event of KNOWN) {
      const ctx = observe(newContext(), event);
      const caption = captionFor(event, ctx);
      const silent = isSilent(event);
      assert.ok(
        caption !== null || silent,
        `${event.component}.${event.type} has no caption and is not marked silent`,
      );
      if (silent) assert.equal(caption, null, `${event.type} is silent`);
    }
  });

  it("captions are one plain sentence with no IDs, addresses or sats", () => {
    const all = [
      ...captionAll(FIXTURE).items.map((i) => i.caption.text),
      ...KNOWN.flatMap((e) => {
        const c = captionFor(e, observe(newContext(), e));
        return c ? [c.text] : [];
      }),
    ];
    assert.ok(all.length > 20);
    for (const line of all) {
      assert.doesNotMatch(line, /bcrt1|bc1q/, line);
      assert.doesNotMatch(line, /\b[0-9a-f]{8,}\b/i, line);
      assert.doesNotMatch(line, /\bsats?\b/i, line);
      assert.doesNotMatch(line, /shopper-|nonce|psbt|txid/i, line);
      assert.match(line, /^[A-Z]/, line);
      assert.match(line, /\.$/, line);
    }
  });

  it("narrates a budget grant the way the room should hear it", () => {
    const lines = text(FIXTURE.slice(0, 40));
    assert.ok(lines.includes("Your agent is asking for a $200 budget."));
    assert.ok(
      lines.includes("Your laptop is asking the Ledger to approve a $200 budget."),
    );
    assert.ok(lines.includes("Approved on your Ledger. The device signed the plan."));
    assert.ok(
      lines.includes(
        "The vault checked your Ledger signature and released one budget key.",
      ),
    );
    assert.ok(lines.includes("Your agent can now spend up to $200 on its own."));
  });

  it("the everyday purchase is the green big moment", () => {
    const items = captionAll(FIXTURE).items.filter((i) => i.caption.moment);
    const purchase = items.find((i) => i.caption.moment === "purchase");
    assert.ok(purchase);
    assert.equal(purchase.caption.tone, "good");
    assert.equal(
      purchase.caption.text,
      "Your agent paid $179 from its $200 budget. No Ledger tap needed.",
    );
  });

  it("the drain during a compromise is red and never shown as a purchase", () => {
    const items = captionAll(FIXTURE).items;
    const purchases = items.filter((i) => i.caption.moment === "purchase");
    assert.equal(purchases.length, 1);
    const drain = items.find((i) => i.caption.moment === "compromise");
    assert.ok(drain);
    assert.equal(drain.caption.tone, "bad");
    assert.equal(drain.caption.simulation, true);
    assert.deepEqual(drain.caption.nodes, ["agent", "attacker"]);
  });

  it("a rejected attacker request reads as the user asked", () => {
    let ctx: StoryContext = newContext();
    const events = [
      ev("agent", "compromise_started", { agent_id: "a" }),
      ev("agent", "compromise_large_spend_requested", { amount_sats: 5_000_000 }),
      ev("approver", "approval_rejected", {}),
      ev("agent", "compromise_large_spend_blocked", { stage: "approval" }),
      ev("agent", "compromise_finished", {}),
    ];
    const lines: string[] = [];
    for (const e of events) {
      ctx = observe(ctx, e);
      const c = captionFor(e, ctx);
      if (c) lines.push(c.text);
    }
    assert.equal(lines[lines.length - 1], "Request for $5,000 more: rejected on your Ledger.");
    assert.ok(!lines.some((l) => l.startsWith("Rejected on your Ledger")));
  });

  it("the vault block is the red big moment", () => {
    const blocked = captionAll(FIXTURE).items.find(
      (i) => i.caption.moment === "blocked",
    );
    assert.ok(blocked);
    assert.equal(blocked.caption.tone, "bad");
    assert.deepEqual(blocked.caption.nodes, ["signer", "vault"]);
    assert.match(blocked.caption.text, /^Vault blocked the transaction/);
  });

  it("an honest signature check matches the user's wording", () => {
    const e = ev("vault", "verification_passed", {});
    assert.equal(
      captionFor(e, newContext())?.text,
      "The vault checked the signer's signature: it matches.",
    );
  });

  it("large spend approvals state the amount from the plan text", () => {
    const e = ev("approver", "approval_requested", {
      kind: "large_spend",
      text: "Pay 0.00799 BTC to bcrt1q729d...t6l6fw for Featherbook 13, PSBT 77aa88bb. Nonce 11",
    });
    assert.equal(
      captionFor(e, newContext())?.text,
      "Your laptop is asking the Ledger to approve paying $799 from main funds.",
    );
  });
});
