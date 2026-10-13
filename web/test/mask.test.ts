import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { maskSecrets } from "../lib/mask.ts";

describe("maskSecrets", () => {
  it("masks bcrt1 and bc1 addresses", () => {
    const text = "sent to bcrt1qxy2kgdygjrsqtzq2n0yrf2493p83kkfjhx0wlh";
    assert.ok(!maskSecrets(text).includes("bcrt1"));
    const main = "paid bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4 ok";
    assert.ok(!maskSecrets(main).includes("bc1qw508"));
  });

  it("masks 64-hex strings", () => {
    const txid = "ab".repeat(32);
    assert.equal(
      maskSecrets(`tx ${txid} done`),
      "tx ·id hidden· done",
    );
  });

  it("masks order ids and 0x addresses", () => {
    const order = "a2e8f1ccb4724e4a86c8ad2a7e19b4ae";
    assert.equal(maskSecrets(`Order ${order}.`), "Order ·id hidden·.");
    assert.ok(
      !maskSecrets("to 0xdad77910dbdfde764fc21fcd4e74d71bbaca6d8d").includes("dad779"),
    );
  });

  it("leaves normal text and short references alone", () => {
    const text = "Your order 5f3a is on the way for $179.";
    assert.equal(maskSecrets(text), text);
  });

  it("masks several occurrences", () => {
    const text = `${"cd".repeat(32)} and ${"ef".repeat(32)}`;
    assert.equal(
      (maskSecrets(text).match(/·id hidden·/g) ?? []).length,
      2,
    );
  });
});
