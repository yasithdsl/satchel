import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { retryWhileBusy } from "../lib/retry.ts";

const noSleep = () => Promise.resolve();

describe("retryWhileBusy", () => {
  it("returns the first success", async () => {
    let calls = 0;
    const result = await retryWhileBusy(
      async () => ++calls * 10,
      { sleep: noSleep },
    );
    assert.equal(result, 10);
    assert.equal(calls, 1);
  });

  it("retries 409 busy errors until success", async () => {
    let calls = 0;
    const result = await retryWhileBusy(
      async () => {
        calls += 1;
        if (calls < 3) throw new Error("compromise: 409");
        return "ok";
      },
      { sleep: noSleep },
    );
    assert.equal(result, "ok");
    assert.equal(calls, 3);
  });

  it("does not retry other errors", async () => {
    let calls = 0;
    await assert.rejects(
      retryWhileBusy(
        async () => {
          calls += 1;
          throw new Error("compromise: 500");
        },
        { sleep: noSleep },
      ),
      /500/,
    );
    assert.equal(calls, 1);
  });

  it("gives up after the budget", async () => {
    let calls = 0;
    await assert.rejects(
      retryWhileBusy(
        async () => {
          calls += 1;
          throw new Error("compromise: 409");
        },
        { budgetMs: 0, sleep: noSleep },
      ),
      /409/,
    );
    assert.equal(calls, 1);
  });
});
