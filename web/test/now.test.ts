import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { nowBanner } from "../lib/now.ts";
import type { XrayEvent } from "../lib/xray.ts";

const NOW = Date.parse("2026-10-12T20:00:00.000+00:00");

function ev(
  seq: number,
  type: string,
  component = "agent",
  extra: Partial<XrayEvent> = {},
  ts = "2026-10-12T20:00:00.000+00:00",
): XrayEvent {
  return {
    seq,
    id: `id-${seq}`,
    ts,
    component,
    type,
    message: `m ${type}`,
    payload: {},
    ...extra,
  };
}

describe("now banner", () => {
  it("shows a pending approval first", () => {
    const b = nowBanner({
      pendingText: "Give shopper-1 envelope #1",
      events: [ev(1, "approval_requested", "approver")],
      now: NOW,
    });
    assert.equal(b.tone, "amber");
    assert.match(b.text, /Approval needed on your Ledger/);
    assert.match(b.text, /Give shopper-1 envelope #1/);
  });

  it("surfaces a recent vault block in red", () => {
    const b = nowBanner({
      pendingText: null,
      events: [
        ev(
          1,
          "verification_failed",
          "vault",
          {
            alert: {
              level: "error",
              title: "Vault blocked this transaction",
              reasons: ["nonce mismatch"],
            },
          },
          NOW - 10_000 > 0
            ? "2026-10-12T19:59:50.000+00:00"
            : "",
        ),
      ],
      now: NOW,
    });
    assert.equal(b.tone, "red");
    assert.match(b.text, /Vault blocked this transaction/);
  });

  it("ignores vault blocks older than a minute", () => {
    const b = nowBanner({
      pendingText: null,
      events: [
        ev(
          1,
          "verification_failed",
          "vault",
          {
            alert: {
              level: "error",
              title: "Vault blocked this transaction",
              reasons: ["nonce mismatch"],
            },
          },
          "2026-10-12T19:58:00.000+00:00",
        ),
      ],
      now: NOW,
    });
    assert.equal(b.tone, "neutral");
    assert.match(b.text, /Vault blocked the transaction/);
  });

  it("shows SIMULATION while a compromise is running", () => {
    const b = nowBanner({
      pendingText: null,
      events: [
        ev(1, "compromise_started", "agent", { simulation: true }),
        ev(
          2,
          "compromise_envelope_drained",
          "agent",
          { simulation: true },
        ),
      ],
      now: NOW,
    });
    assert.equal(b.tone, "amber");
    assert.match(b.text, /SIMULATION/);
  });

  it("stops showing SIMULATION after compromise_finished", () => {
    const b = nowBanner({
      pendingText: null,
      events: [
        ev(1, "compromise_started", "agent", { simulation: true }),
        ev(
          2,
          "compromise_finished",
          "agent",
          { simulation: true },
        ),
      ],
      now: NOW,
    });
    assert.match(b.text, /SIMULATION over/);
  });

  it("falls back to the latest story line", () => {
    const b = nowBanner({
      pendingText: null,
      events: [
        ev(1, "order_paid", "marketplace"),
        ev(2, "block_mined", "network"),
      ],
      now: NOW,
    });
    assert.equal(b.text, "A block was mined");
  });

  it("defaults to waiting for the shopper", () => {
    const b = nowBanner({ pendingText: null, events: [], now: NOW });
    assert.equal(b.text, "Waiting for the shopper");
  });
});
