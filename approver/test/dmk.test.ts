import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { Subject } from "rxjs";
import {
  DeviceActionStatus,
  DeviceActionTimeout,
  isDeviceRejection,
  runAction,
} from "../src/dmk.ts";

describe("isDeviceRejection", () => {
  it("detects RefusedByUserDAError tag", () => {
    assert.ok(isDeviceRejection({ _tag: "RefusedByUserDAError" }));
  });

  it("detects rejection status words at the top level", () => {
    for (const code of ["5501", "6985", "6982"]) {
      assert.ok(isDeviceRejection({ errorCode: code }), code);
    }
  });

  it("detects rejection nested in originalError", () => {
    assert.ok(
      isDeviceRejection({
        _tag: "UnknownDeviceExchangeError",
        originalError: { errorCode: "6985" },
      }),
    );
  });

  it("does not classify other errors as rejections", () => {
    assert.equal(isDeviceRejection({ _tag: "DeviceLockedError" }), false);
    assert.equal(isDeviceRejection({ errorCode: "6807" }), false);
    assert.equal(isDeviceRejection(new Error("boom")), false);
    assert.equal(isDeviceRejection(undefined), false);
  });
});

describe("runAction", () => {
  it("reports a timeout as a timeout even though cancel emits Stopped", async () => {
    const subject = new Subject<{ status: unknown }>();
    let cancelled = false;
    const action = {
      observable: subject as never,
      cancel: () => {
        cancelled = true;
        subject.next({ status: DeviceActionStatus.Stopped });
      },
    };
    await assert.rejects(runAction(action, 20), DeviceActionTimeout);
    assert.ok(cancelled);
  });
});
