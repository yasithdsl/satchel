import assert from "node:assert/strict";
import { describe, it } from "node:test";
import {
  componentColor,
  eventAnimation,
  feedLabel,
  type XrayEvent,
} from "../lib/xray.ts";

function ev(nodes: XrayEvent["nodes"]): XrayEvent {
  return {
    seq: 1,
    id: "x",
    ts: "2026-10-12T20:00:00.000+00:00",
    component: "laptop",
    type: "hop",
    message: "m",
    payload: null,
    nodes,
  };
}

describe("xray event mapping", () => {
  it("maps from/to nodes to glow + edge", () => {
    const a = eventAnimation(ev({ from: "vault", to: "laptop" }));
    assert.deepEqual(a.glow.sort(), ["laptop", "vault"]);
    assert.deepEqual(a.edge, { from: "vault", to: "laptop" });
  });

  it("maps at nodes to a single glow", () => {
    const a = eventAnimation(ev({ at: "ledger" }));
    assert.deepEqual(a.glow, ["ledger"]);
    assert.equal(a.edge, null);
  });

  it("returns nothing when nodes is absent", () => {
    assert.deepEqual(eventAnimation(ev(undefined)), {
      glow: [],
      edge: null,
    });
  });

  it("feed uses label over message", () => {
    const e = ev(undefined);
    e.label = "Vault → laptop: list";
    assert.equal(feedLabel(e), "Vault → laptop: list");
    delete e.label;
    assert.equal(feedLabel(e), "m");
  });

  it("component colors are stable", () => {
    assert.ok(componentColor("agent").includes("violet"));
    assert.ok(componentColor("vault").includes("amber"));
    assert.ok(componentColor("nope").includes("neutral"));
  });
});
