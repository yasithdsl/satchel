import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { EventStore } from "../lib/store.ts";
import type { XrayEvent } from "../lib/xray.ts";

function ev(seq: number, boot = "b1"): XrayEvent {
  return {
    seq,
    id: `id-${seq}`,
    ts: "2026-10-12T20:00:00.000+00:00",
    component: "laptop",
    type: "hop",
    message: `m${seq}`,
    payload: null,
    boot,
  };
}

describe("event store", () => {
  it("dedupes events by seq", () => {
    const store = new EventStore();
    store.ingest(ev(1));
    store.ingest(ev(2));
    store.ingest(ev(1));
    assert.equal(store.size, 2);
    assert.deepEqual(
      store.snapshot.map((e) => e.seq),
      [1, 2],
    );
  });

  it("keeps ascending seq order in the snapshot", () => {
    const store = new EventStore();
    store.ingest(ev(3));
    store.ingest(ev(1));
    store.ingest(ev(2));
    assert.deepEqual(
      store.snapshot.map((e) => e.seq),
      [1, 2, 3],
    );
  });

  it("clears the store when the boot id changes", () => {
    const store = new EventStore();
    store.ingest(ev(1, "old"));
    store.ingest(ev(2, "old"));
    store.ingest(ev(1, "new"));
    assert.equal(store.size, 1);
    assert.deepEqual(store.snapshot[0].boot, "new");
    store.ingest(ev(2, "new"));
    assert.equal(store.size, 2);
  });

  it("tracks the last seq for Last-Event-ID resume", () => {
    const store = new EventStore();
    store.ingest(ev(5));
    assert.equal(store.lastSeq, 5);
    store.ingest(ev(3));
    assert.equal(store.lastSeq, 5);
  });

  it("notifies subscribers once per burst of ingests", async () => {
    const store = new EventStore();
    let calls = 0;
    const unsub = store.subscribe(() => calls++);
    for (let seq = 1; seq <= 50; seq++) store.ingest(ev(seq));
    assert.equal(calls, 0);
    await new Promise((r) => setTimeout(r, 5));
    assert.equal(calls, 1);
    assert.equal(store.snapshot.length, 50);
    unsub();
    store.ingest(ev(51));
    await new Promise((r) => setTimeout(r, 5));
    assert.equal(calls, 1);
  });

  it("reset clears everything", () => {
    const store = new EventStore();
    store.ingest(ev(4));
    store.reset();
    assert.equal(store.size, 0);
    assert.equal(store.lastSeq, 0);
    assert.deepEqual(store.snapshot, []);
  });
});
