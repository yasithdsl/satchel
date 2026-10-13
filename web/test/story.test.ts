import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { satsToUsd, storyLine } from "../lib/story.ts";
import type { XrayEvent } from "../lib/xray.ts";

function ev(
  component: string,
  type: string,
  payload: Record<string, unknown> | null = null,
  extra: Partial<XrayEvent> = {},
): XrayEvent {
  return {
    seq: 1,
    id: "x",
    ts: "2026-10-12T20:00:00.000+00:00",
    component,
    type,
    message: `msg ${type}`,
    payload,
    ...extra,
  };
}

function hop(type: string, from: string, to: string): XrayEvent {
  return ev("laptop", type, {
    flow_id: "f1",
    hop: 0,
    from,
    to,
  });
}

describe("story mapping", () => {
  it("request_budget names the dollar amount", () => {
    const line = storyLine(
      ev("agent", "tool_call", {
        tool: "request_budget",
        input: { amount_usd: 200 },
      }),
    );
    assert.equal(
      line?.text,
      "Agent asked for a $200 prepaid budget",
    );
  });

  it("approval_requested quotes the plan text", () => {
    const line = storyLine(
      ev("approver", "approval_requested", {
        kind: "envelope_release",
        text: "Give shopper-1 envelope #1",
        nonce: "n",
      }),
    );
    assert.equal(
      line?.text,
      "Your Ledger shows: “Give shopper-1 envelope #1”",
    );
    assert.equal(line?.tone, "warn");
  });

  it("approval granted and rejected", () => {
    assert.equal(
      storyLine(ev("approver", "approval_granted", {}))?.text,
      "You approved on the Ledger",
    );
    const rejected = storyLine(
      ev("approver", "approval_rejected", {}),
    );
    assert.equal(rejected?.text, "You rejected on the Ledger");
  });

  it("laptop hops", () => {
    assert.equal(
      storyLine(hop("approval_sent_to_vault", "laptop", "vault"))
        ?.text,
      "Laptop passed your signed approval to the vault",
    );
    assert.equal(
      storyLine(
        hop("key_delivered_to_agent", "laptop", "agent:x"),
      )?.text,
      "Envelope key handed to the agent (key hidden)",
    );
    assert.equal(
      storyLine(hop("psbt_built", "laptop", "laptop"))?.text,
      "Laptop built an unsigned transaction from your main funds",
    );
    assert.equal(
      storyLine(hop("keys_sent_to_signer", "laptop", "signer"))
        ?.text,
      "Laptop sent the transaction and those keys to the signer",
    );
    assert.equal(
      storyLine(hop("broadcast", "laptop", "node"))?.text,
      "Verified transaction broadcast",
    );
    assert.equal(
      storyLine(hop("envelopes_fetched", "vault", "laptop")),
      null,
    );
  });

  it("vault events", () => {
    assert.equal(
      storyLine(
        ev("vault", "envelope_released", {
          envelope_index: 1,
          agent_id: "a",
          nonce: "n",
        }),
      )?.text,
      "Vault checked your Ledger signature and released envelope #1",
    );
    const refused = storyLine(
      ev("vault", "release_refused", { reason: "bad signature" }),
    );
    assert.equal(
      refused?.text,
      "Vault refused to release keys: bad signature",
    );
    assert.equal(refused?.tone, "bad");
    assert.equal(
      storyLine(ev("vault", "spend_keys_released", {}))?.text,
      "Vault released signing keys for this payment only",
    );
    assert.equal(
      storyLine(ev("vault", "verification_passed", {}))?.text,
      "Vault re-checked every signature: all match",
    );
    const failed = storyLine(
      ev("vault", "verification_failed", {
        reasons: ["nonce mismatch"],
      }),
    );
    assert.equal(
      failed?.text,
      "Vault blocked the transaction: nonce mismatch",
    );
    assert.equal(failed?.tone, "bad");
  });

  it("agent tool calls and payment", () => {
    assert.equal(
      storyLine(
        ev("agent", "tool_call", {
          tool: "search_products",
          input: { query: "headphones" },
        }),
      )?.text,
      "Agent searched the shop for “headphones”",
    );
    assert.equal(
      storyLine(
        ev("agent", "tool_call", {
          tool: "suggest_products",
          input: { product_ids: ["a", "b", "c"] },
        }),
      )?.text,
      "Agent suggested 3 products",
    );
    assert.equal(
      storyLine(
        ev("agent", "payment_sent", { amount_sats: 179_000 }),
      )?.text,
      "Agent paid $179 from its envelope",
    );
    assert.equal(
      storyLine(
        ev(
          "agent",
          "payment_sent",
          { amount_sats: 20_000 },
          { nodes: { to: "losssink" } },
        ),
      ),
      null,
    );
    assert.equal(
      storyLine(ev("agent", "large_purchase_notice", {}))?.text,
      "Too big for the envelope: needs your approval on the Ledger",
    );
  });

  it("marketplace events", () => {
    assert.equal(
      storyLine(ev("marketplace", "order_created", {}))?.text,
      "Shop created an order",
    );
    assert.equal(
      storyLine(ev("marketplace", "payment_seen", {}))?.text,
      "Shop sees the payment, waiting for a block",
    );
    assert.equal(
      storyLine(ev("marketplace", "order_paid", {}))?.text,
      "Order paid",
    );
  });

  it("signer events", () => {
    assert.equal(
      storyLine(
        ev("signer", "psbt_signed", { nonce: "rfc6979" }),
      )?.text,
      "Signer signed the transaction",
    );
    assert.equal(
      storyLine(
        ev("signer", "psbt_signed", { nonce: "random" }),
      )?.text,
      "Signer signed the transaction with random nonces",
    );
    assert.equal(
      storyLine(ev("signer", "random_nonce_enabled", {}))?.text,
      "Malicious signer mode on (demo)",
    );
    assert.equal(
      storyLine(ev("signer", "random_nonce_disabled", {}))?.text,
      "Malicious signer mode off (demo)",
    );
  });

  it("network block_mined", () => {
    assert.equal(
      storyLine(ev("network", "block_mined", {}))?.text,
      "A block was mined",
    );
  });

  it("compromise events are tagged simulation", () => {
    const started = storyLine(
      ev("agent", "compromise_started", {}, { simulation: true }),
    );
    assert.equal(
      started?.text,
      "SIMULATION: an attacker has taken over the agent",
    );
    assert.equal(started?.tone, "sim");
    assert.equal(
      storyLine(
        ev(
          "agent",
          "compromise_envelope_drained",
          { amount_sats: 20_498 },
          { simulation: true },
        ),
      )?.text,
      "SIMULATION: attacker drained the envelope, $20.50 sent to the loss sink",
    );
    assert.equal(
      storyLine(
        ev(
          "agent",
          "compromise_envelope_empty",
          {},
          { simulation: true },
        ),
      )?.text,
      "SIMULATION: envelope already empty",
    );
    assert.equal(
      storyLine(
        ev(
          "agent",
          "compromise_large_spend_requested",
          { amount_sats: 5_000_000 },
          { simulation: true },
        ),
      )?.text,
      "SIMULATION: attacker asked for $5,000 from your main funds",
    );
    assert.equal(
      storyLine(
        ev(
          "agent",
          "compromise_large_spend_blocked",
          {},
          { simulation: true },
        ),
      )?.text,
      "Blocked: the request never got past your Ledger, main funds untouched",
    );
    assert.equal(
      storyLine(
        ev(
          "agent",
          "compromise_large_spend_approved",
          {},
          { simulation: true },
        ),
      )?.text,
      "Approved on the Ledger: main funds moved",
    );
    assert.equal(
      storyLine(
        ev(
          "agent",
          "compromise_finished",
          {},
          { simulation: true },
        ),
      )?.text,
      "SIMULATION over: the loss stayed within the envelope",
    );
  });

  it("unmapped events stay out of the story", () => {
    assert.equal(storyLine(ev("vault", "vault_unlocked", {})), null);
    assert.equal(
      storyLine(ev("agent", "tool_result", { tool: "search" })),
      null,
    );
    assert.equal(storyLine(ev("laptop", "setup_completed", {})), null);
  });

  it("formats sats as dollars at 1000 sats per dollar", () => {
    assert.equal(satsToUsd(200_000), "$200");
    assert.equal(satsToUsd(20_498), "$20.50");
    assert.equal(satsToUsd(100_000_000), "$100,000");
  });
});
