import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { SseParser } from "../lib/sse.ts";

describe("SseParser", () => {
  it("parses a single event", () => {
    const p = new SseParser();
    assert.deepEqual(p.feed('data: {"a":1}\n\n'), [
      { id: null, data: '{"a":1}' },
    ]);
  });

  it("handles events split across chunks", () => {
    const p = new SseParser();
    assert.deepEqual(p.feed('data: {"a'), []);
    assert.deepEqual(p.feed('":1}\n\n'), [
      { id: null, data: '{"a":1}' },
    ]);
  });

  it("parses multiple events in one chunk", () => {
    const p = new SseParser();
    assert.deepEqual(
      p.feed("data: one\n\ndata: two\n\n"),
      [
        { id: null, data: "one" },
        { id: null, data: "two" },
      ],
    );
  });

  it("joins multi-line data and captures id", () => {
    const p = new SseParser();
    assert.deepEqual(
      p.feed("id: 7\ndata: first\ndata: second\n\n"),
      [{ id: "7", data: "first\nsecond" }],
    );
  });

  it("ignores comments and incomplete trailing data", () => {
    const p = new SseParser();
    assert.deepEqual(p.feed(": keepalive\n\ndata: ok\n"), []);
    assert.deepEqual(p.feed("\n"), [{ id: null, data: "ok" }]);
  });
});
