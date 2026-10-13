import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { describe, it } from "node:test";
import {
  captionAll,
  captionFor,
  isSilent,
  newContext,
  observe,
  SATCHEL_STEPS,
  type Captioned,
  type StoryContext,
} from "../lib/caption.ts";
import type { XrayEvent } from "../lib/xray.ts";

/** A real three-scene run against the demo stack (scripts/demo_reset.py). */
const FIXTURE = JSON.parse(
  readFileSync(new URL("./fixtures/demo-events.json", import.meta.url), "utf8"),
) as XrayEvent[];
const ITEMS = captionAll(FIXTURE).items;

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

function texts(items: Captioned[] = ITEMS): string[] {
  return items.map((i) => i.caption.text);
}

function find(text: string | RegExp): Captioned {
  const hit = ITEMS.find((i) =>
    typeof text === "string" ? i.caption.text === text : text.test(i.caption.text),
  );
  assert.ok(hit, `no step reads ${text}`);
  return hit;
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
  ev("approver", "approval_requested", {
    kind: "satchel_grant",
    text: "Create a 0.002 BTC satchel #0 for x from main funds, expires 13 Oct 10:10 UTC. Nonce 1",
  }),
  ev("approver", "approval_granted", {}),
  ev("approver", "approval_rejected", {}),
  ev("approver", "approval_failed", {}),
  ...[
    "satchel_reserved",
    "plan_sent_to_approver",
    "approval_received",
    "approval_rejected",
    "approval_sent_to_vault",
    "key_release_received",
    "key_delivered_to_agent",
    "change_address_exported",
    "utxos_selected",
    "psbt_built",
    "keys_released",
    "keys_sent_to_signer",
    "signed_tx_received",
    "verification_received",
    "funding_confirmed",
    "funding_proof_sent",
    "receive_addresses_exported",
    "main_funds_funded",
  ].map((type) => ev("laptop", type, { flow_id: "f", flow: "grant" })),
  ev("laptop", "broadcast", { flow_id: "f", flow: "spend" }),
  ...[
    "main_fund_funded",
    "grant_completed",
    "grant_failed",
    "spend_completed",
    "spend_failed",
    "setup_completed",
  ].map((type) => ev("laptop", type, {})),
  ...[
    "seed_created",
    "vault_unlocked",
    "unlock_failed",
    "vault_reset",
    "envelopes_exported",
    "addresses_exported",
    "release_requested",
  ].map((type) => ev("vault", type)),
  ev("vault", "satchel_reserved", { envelope_index: 0, path: "m/84'/1'/0'/2'/0'", budget_sats: 200_000 }),
  ev("vault", "satchel_funding_released", { envelope_index: 0 }),
  ev("vault", "satchel_released", { envelope_index: 0 }),
  ev("vault", "release_refused", { reason: "bad signature" }),
  ev("vault", "spend_keys_released", {}),
  ev("vault", "verification_passed", {}),
  ev("vault", "verification_failed", { reasons: ["mismatch"] }),
  ev("signer", "psbt_signed", { nonce: "rfc6979" }),
  ev("signer", "random_nonce_signing", {}),
  ev("signer", "random_nonce_enabled", {}),
  ev("signer", "random_nonce_disabled", {}),
  ev("signer", "sign_refused", {}),
  ev("marketplace", "search", { results: [] }),
  ev("marketplace", "order_created", {}),
  ev("marketplace", "payment_seen", {}),
  ev("marketplace", "order_paid", {}),
  ev("network", "block_mined", {}),
];

describe("captions", () => {
  it("every known event type is either captioned or deliberately silent", () => {
    for (const event of KNOWN) {
      const caption = captionFor(event, observe(newContext(), event));
      const silent = isSilent(event);
      assert.ok(
        caption !== null || silent,
        `${event.component}.${event.type} has no caption and is not marked silent`,
      );
      if (silent) assert.equal(caption, null, `${event.type} is silent`);
    }
  });

  it("headlines and explanations never show IDs, addresses or sats", () => {
    const all = [
      ...ITEMS.map((i) => i.caption),
      ...KNOWN.flatMap((e) => {
        const c = captionFor(e, observe(newContext(), e));
        return c ? [c] : [];
      }),
    ];
    assert.ok(all.length > 40);
    for (const { text, why } of all) {
      for (const line of [text, why ?? ""]) {
        assert.doesNotMatch(line, /bcrt1|bc1q/, line);
        assert.doesNotMatch(line, /\b[0-9a-f]{8,}\b/i, line);
        assert.doesNotMatch(line, /\bsats?\b/i, line);
        // "nonce" the concept may appear (Dark Skippy); an approval's nonce id may not.
        assert.doesNotMatch(line, /shopper-|nonce [0-9a-f]|psbt|txid/i, line);
      }
      assert.match(text, /^[A-Z].*\.$/, text);
    }
  });

  it("narrates satchel creation as eleven numbered steps, every time", () => {
    const satchel = ITEMS.filter((i) => i.caption.chapter === "satchel");
    assert.equal(satchel.length, SATCHEL_STEPS.length * 3);
    for (let run = 0; run < 3; run++) {
      const steps = satchel.slice(run * 11, run * 11 + 11);
      assert.deepEqual(
        steps.map((s) => s.caption.step?.index),
        [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11],
      );
    }
    assert.deepEqual(texts(satchel.slice(0, 11)), [
      "Your agent asks for a $200 budget.",
      "The vault creates a fresh key for a new satchel.",
      "Your laptop drafts the funding: $200 from main funds into the satchel.",
      "Your laptop asks the Ledger to approve a $200 satchel.",
      "Approved on your Ledger.",
      "The vault checks your signature and the plan, then releases one-time keys.",
      "The offline signer signs it with those one-time keys.",
      "The vault checks the signer's signature: it matches.",
      "The $200 funding is sent and confirmed in a block.",
      "The vault hands over the satchel key.",
      "Your agent now holds a $200 satchel.",
    ]);
    assert.match(satchel[1].caption.why ?? "", /Fully hardened path m\/84'\/1'\/0'\/2'\/0'\./);
    assert.match(satchel[3].caption.why ?? "", /One tap covers it all/);
    assert.equal(satchel[10].ctx.satchel.milestones.length, 9);
  });

  it("shows the agent shopping inside the satchel", () => {
    const search = find("Your agent browses the store for headphones under $200.");
    assert.equal(search.caption.visual, "store");
    const pick = find("It checks out: Aurora ANC Wireless Headphones, $179.");
    assert.equal(pick.caption.why, "$179 fits in its $200 satchel, so it can pay on its own.");
    assert.equal(pick.ctx.store.results.length, 5);
    assert.equal(pick.ctx.store.suggested[0], "aurora-anc-wireless-headphones");
    const paid = find("Paid $179 from the satchel. No Ledger tap needed.");
    assert.equal(paid.caption.moment, "purchase");
    assert.equal(paid.caption.tone, "good");
    assert.equal(paid.caption.why, "$21 is left in the satchel. Your main funds were never touched.");
  });

  it("explains the attack, and the loss stops at the satchel", () => {
    const intro = find("Simulated attack: your agent is fully compromised.");
    assert.equal(intro.caption.visual, "attack");
    assert.match(intro.caption.why ?? "", /What can they take\?/);
    const drain = ITEMS.find((i) => i.caption.moment === "compromise");
    assert.ok(drain);
    assert.deepEqual(drain.caption.nodes, ["agent", "attacker"]);
    assert.equal(drain.ctx.attack.budgetSats, 200_000);
    const blocked = find("Request for $5,000 more: rejected on your Ledger.");
    assert.equal(blocked.caption.why, "Lost: the $200 satchel. Main funds: untouched.");
    assert.equal(blocked.ctx.attack.outcome, "rejected");
    assert.equal(
      ITEMS.filter((i) => i.caption.moment === "purchase").length,
      1,
      "the attacker's drain is never shown as a purchase",
    );
  });

  it("explains Dark Skippy and shows the vault catching the forged signature", () => {
    const rigged = find("Simulated attack: the signer is rigged.");
    assert.match(rigged.caption.why ?? "", /Dark Skippy/);
    const forged = find("The signer signs it, but not the honest way.");
    assert.equal(forged.caption.visual, "signer");
    const blocked = ITEMS.find((i) => i.caption.moment === "blocked");
    assert.ok(blocked);
    assert.match(blocked.caption.text, /^Vault blocked the transaction/);
    assert.equal(blocked.ctx.signer.verdict, "forged");
  });

  it("an honest signature check matches the user's wording", () => {
    const e = ev("vault", "verification_passed", {});
    assert.equal(
      captionFor(e, newContext())?.text,
      "The vault checks the signer's signature: it matches.",
    );
  });

  it("a rejected attacker request reads as the user asked", () => {
    let ctx: StoryContext = newContext();
    const lines: string[] = [];
    for (const e of [
      ev("agent", "compromise_started", { agent_id: "a" }),
      ev("agent", "compromise_large_spend_requested", { amount_sats: 5_000_000 }),
      ev("approver", "approval_rejected", {}),
      ev("agent", "compromise_large_spend_blocked", { stage: "approval" }),
      ev("agent", "compromise_finished", {}),
    ]) {
      ctx = observe(ctx, e);
      const c = captionFor(e, ctx);
      if (c) lines.push(c.text);
    }
    assert.equal(lines[lines.length - 1], "Request for $5,000 more: rejected on your Ledger.");
    assert.ok(!lines.some((l) => l.startsWith("Rejected on your Ledger")));
  });

  it("main-fund approvals state the amount from the plan text", () => {
    const e = ev("approver", "approval_requested", {
      kind: "large_spend",
      text: "Pay 0.00799 BTC to bcrt1q729d...t6l6fw for Featherbook 13, PSBT 77aa88bb. Nonce 11",
    });
    assert.equal(
      captionFor(e, newContext())?.text,
      "Your laptop asks the Ledger to approve paying $799 from main funds.",
    );
  });
});
