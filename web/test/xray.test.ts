import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { feedTime } from "../lib/xray.ts";

describe("xray helpers", () => {
  it("formats event times as a clock", () => {
    assert.match(feedTime("2026-10-12T20:00:05.000+00:00"), /^\d{2}:\d{2}:05$/);
    assert.equal(feedTime("not a time"), "not a time");
  });
});
