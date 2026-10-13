import assert from "node:assert/strict";
import { describe, it } from "node:test";
import {
  classifyRelease,
  movedBeyondSwipe,
  screenKind,
  toDevicePoint,
} from "../lib/device.ts";

describe("ledger device gestures", () => {
  const rect = { left: 0, top: 0, width: 240, height: 300 };

  it("maps client coordinates to the 480x600 device space", () => {
    assert.deepEqual(toDevicePoint(120, 150, rect), {
      x: 240,
      y: 300,
    });
    assert.deepEqual(toDevicePoint(0, 0, rect), { x: 0, y: 0 });
    assert.deepEqual(toDevicePoint(240, 300, rect), {
      x: 479,
      y: 599,
    });
  });

  it("detects movement beyond the swipe threshold", () => {
    assert.equal(movedBeyondSwipe(21, 0), true);
    assert.equal(movedBeyondSwipe(15, 15), true);
    assert.equal(movedBeyondSwipe(20, 0), false);
    assert.equal(movedBeyondSwipe(5, 5), false);
  });

  it("classifies a quick tap", () => {
    assert.deepEqual(
      classifyRelease({ x: 100, y: 100 }, { x: 102, y: 99 }, false),
      { kind: "tap", x: 100, y: 100 },
    );
  });

  it("classifies a swipe with start/end and delay", () => {
    assert.deepEqual(
      classifyRelease({ x: 400, y: 300 }, { x: 80, y: 305 }, false),
      {
        kind: "swipe",
        x: 400,
        y: 300,
        x2: 80,
        y2: 305,
        delay: 0.3,
      },
    );
  });

  it("releases a held press even if it later moved", () => {
    assert.deepEqual(
      classifyRelease({ x: 200, y: 500 }, { x: 120, y: 480 }, true),
      { kind: "release", x: 200, y: 500 },
    );
  });
});

describe("ledger screen kinds", () => {
  it("the Ethereum app home screen is never shown to the audience", () => {
    assert.equal(
      screenKind([
        "Ethereum",
        "This app enables signing",
        "transactions on the Ethereum",
        "network.",
        "Quit app",
      ]),
      "home",
    );
  });

  it("an empty screen (splash or loading) is blank", () => {
    assert.equal(screenKind([]), "blank");
    assert.equal(screenKind(["  "]), "blank");
  });

  it("the review cover is the intro", () => {
    assert.equal(screenKind(["Review message", "Swipe to review", "Reject", "1 of 3"]), "intro");
  });

  it("the message page and the hold page are the review", () => {
    assert.equal(
      screenKind(["Message", "Give shopper-", "32150c90 envelope #2 ", "Reject", "2 of 3"]),
      "review",
    );
    assert.equal(screenKind(["Hold to sign message", "Reject"]), "review");
  });
});
