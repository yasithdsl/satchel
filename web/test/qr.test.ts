import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { nextIndex, partAt } from "../lib/qr.ts";

describe("QR part cycling", () => {
  it("cycles through parts", () => {
    const parts = ["a", "b", "c"];
    assert.equal(partAt(parts, 0), "a");
    assert.equal(partAt(parts, 4), "b");
    assert.equal(nextIndex(parts, 0), 1);
    assert.equal(nextIndex(parts, 2), 0);
  });

  it("single part stays at index 0", () => {
    assert.equal(partAt(["only"], 9), "only");
    assert.equal(nextIndex(["only"], 3), 0);
  });

  it("empty parts give null", () => {
    assert.equal(partAt([], 0), null);
    assert.equal(nextIndex([], 0), 0);
  });
});
