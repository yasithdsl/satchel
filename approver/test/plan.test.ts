import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, it } from "node:test";
import {
  checkNonce,
  newNonce,
  renderText,
  validatePlan,
  type Plan,
} from "../src/plan.ts";

const VECTORS = JSON.parse(
  readFileSync(
    fileURLToPath(new URL("../../fixtures/approval_text_vectors.json", import.meta.url)),
    "utf8",
  ),
) as { plan: unknown; nonce: string; text: string }[];

const GRANT: Plan = {
  kind: "envelope_grant",
  envelope_index: 1,
  agent_id: "agent",
  budget_sats: 50_000,
  expires_at: 4_102_444_800,
};

const SPEND: Plan = {
  kind: "large_spend",
  amount_sats: 1000,
  destination: "bcrt1qw508d6qejxtdg4y5r3zarvary0c5xw7kygt080",
  purpose: "test",
  psbt_sha256: "0".repeat(64),
};

describe("renderText vectors", () => {
  for (const [i, v] of VECTORS.entries()) {
    it(`vector ${i + 1}`, () => {
      assert.equal(renderText(validatePlan(v.plan), v.nonce), v.text);
    });
  }
});

describe("validatePlan", () => {
  it("accepts both kinds", () => {
    assert.equal(validatePlan(GRANT).kind, "envelope_grant");
    assert.equal(validatePlan(SPEND).kind, "large_spend");
  });

  const bad: [string, unknown][] = [
    ["not an object", "hello"],
    ["array", []],
    ["missing key", { ...GRANT, budget_sats: undefined }],
    ["extra key", { ...GRANT, extra: 1 }],
    ["bool int", { ...GRANT, envelope_index: true }],
    ["float int", { ...GRANT, envelope_index: 1.5 }],
    ["negative index", { ...GRANT, envelope_index: -1 }],
    ["index too big", { ...GRANT, envelope_index: 2 ** 31 }],
    ["zero budget", { ...GRANT, budget_sats: 0 }],
    ["over budget", { ...GRANT, budget_sats: 2_100_000_000_000_001 }],
    ["non-multiple expiry", { ...GRANT, expires_at: 1_900_000_001 }],
    ["zero expiry", { ...GRANT, expires_at: 0 }],
    ["expiry over cap", { ...GRANT, expires_at: 253_402_300_800 }],
    ["empty agent", { ...GRANT, agent_id: "" }],
    ["newline agent", { ...GRANT, agent_id: "a\nb" }],
    ["emoji agent", { ...GRANT, agent_id: "🚀" }],
    ["long agent", { ...GRANT, agent_id: "a".repeat(33) }],
    ["leading space", { ...GRANT, agent_id: " agent" }],
    ["newline purpose", { ...SPEND, purpose: "laptop\nroot" }],
    ["emoji purpose", { ...SPEND, purpose: "laptop 🚀" }],
    ["mainnet dest", { ...SPEND, destination: SPEND.destination.replace("bcrt1", "bc1") }],
    ["bad dest", { ...SPEND, destination: "bcrt1qqqq" }],
    ["upper hash", { ...SPEND, psbt_sha256: "A".repeat(64) }],
    ["short hash", { ...SPEND, psbt_sha256: "ab" }],
    ["bad kind", { kind: "x" }],
    ["missing kind", { envelope_index: 1 }],
  ];
  for (const [name, plan] of bad) {
    it(`rejects ${name}`, () => {
      assert.throws(() => validatePlan(plan));
    });
  }
});

describe("nonce", () => {
  it("newNonce produces 16 hex chars", () => {
    const n = newNonce();
    assert.match(n, /^[0-9a-f]{16}$/);
    assert.notEqual(newNonce(), newNonce());
  });
  it("checkNonce rejects bad values", () => {
    assert.throws(() => checkNonce("XYZ"));
    assert.throws(() => checkNonce("ABCDEF0123456789"));
    assert.throws(() => checkNonce(1234));
  });
});
