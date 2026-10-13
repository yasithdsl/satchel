import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { btc, btcTextToSats, usd, usdFromDollars } from "../lib/money.ts";

describe("money", () => {
  it("shows whole dollars at the $100k demo rate", () => {
    assert.equal(usd(100_000_000), "$100,000");
    assert.equal(usd(200_000), "$200");
    assert.equal(usd(20_718), "$21");
    assert.equal(usd(0), "$0");
    assert.equal(usd(300), "<$1");
    assert.equal(usdFromDollars(799), "$799");
  });

  it("keeps BTC short", () => {
    assert.equal(btc(179_000), "0.00179 BTC");
    assert.equal(btc(100_000_000), "1 BTC");
  });

  it("parses plan amounts exactly", () => {
    assert.equal(btcTextToSats("0.002"), 200_000);
    assert.equal(btcTextToSats("0.00799"), 799_000);
    assert.equal(btcTextToSats("1"), 100_000_000);
    assert.equal(btcTextToSats("abc"), null);
  });
});
