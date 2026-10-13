import assert from "node:assert/strict";
import { describe, it } from "node:test";
import {
  classifyRelease,
  movedBeyondSwipe,
  screenHint,
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

describe("ledger screen hints", () => {
  it("hold-to-sign screen", () => {
    assert.equal(
      screenHint(["Hold to sign message"]),
      "Press and hold the button to approve",
    );
  });

  it("reject confirmation", () => {
    assert.equal(
      screenHint(["Yes, reject", "Cancel"]),
      "Tap “Yes, reject” to decline",
    );
  });

  it("review start", () => {
    assert.equal(
      screenHint(["Review message"]),
      "Swipe left to read the request",
    );
  });

  it("home screen and empty are idle", () => {
    assert.equal(screenHint(["Ethereum", "Quit app"]), "Idle");
    assert.equal(screenHint([]), "Idle");
  });

  it("pending approval on the home screen waits for the request", () => {
    const waiting = "Waiting for the request to reach the device…";
    assert.equal(screenHint(["Ethereum", "Quit app"], true), waiting);
    assert.equal(screenHint([], true), waiting);
    assert.equal(
      screenHint(["Review message"], true),
      "Swipe left to read the request",
    );
  });

  it("other review pages ask to continue", () => {
    assert.equal(
      screenHint(["Give shopper-1 envelope #1 (0.002 BTC)"]),
      "Swipe to continue",
    );
  });
});
