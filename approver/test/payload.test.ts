import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { describe, it } from "node:test";
import { toHttp } from "../src/payload.ts";

const REPO_ROOT = fileURLToPath(new URL("../../", import.meta.url));

function pythonFromHttp(httpObj: unknown): { t: string; b: unknown } {
  const out = execFileSync(
    "uv",
    [
      "run",
      "python",
      "-c",
      "import json,sys; from satchel_core.payloads import from_http, encode; " +
        "print(encode(from_http(json.load(sys.stdin))))",
    ],
    { cwd: REPO_ROOT, input: JSON.stringify(httpObj), encoding: "utf8" },
  );
  return JSON.parse(out);
}

const BODY = {
  plan: {
    kind: "envelope_grant",
    envelope_index: 2,
    agent_id: "shopping-agent",
    budget_sats: 200000,
    expires_at: 1760292000,
  },
  text: "Give shopping-agent envelope #2 (0.002 BTC), expires 12 Oct 18:00 UTC. Nonce 0123456789abcdef",
  nonce: "0123456789abcdef",
  signature: "0x" + "ab".repeat(64) + "1b",
  address: "0xDad77910DbDFdE764fC21FCD4E74D71bBACA6D8D",
  path: "44'/60'/0'/0/0",
};

describe("toHttp interop", () => {
  it("payload JSON is canonical and sorted", () => {
    const h = toHttp("ledger_approval", BODY);
    assert.equal(h.type, "ledger_approval");
    const obj = JSON.parse(h.payload);
    assert.equal(obj.v, 1);
    assert.equal(obj.t, "ledger_approval");
    assert.deepEqual(
      obj,
      JSON.parse(
        '{"b":{"address":"0xDad77910DbDFdE764fC21FCD4E74D71bBACA6D8D","nonce":"0123456789abcdef","path":"44\'/60\'/0\'/0/0","plan":{"agent_id":"shopping-agent","budget_sats":200000,"envelope_index":2,"expires_at":1760292000,"kind":"envelope_grant"},"signature":"' +
          "0x" + "ab".repeat(64) + '1b","text":"' +
          BODY.text + '"},"t":"ledger_approval","v":1}',
      ),
    );
  });

  it("python from_http decodes a single-part body", () => {
    const decoded = pythonFromHttp(toHttp("ledger_approval", BODY));
    assert.equal(decoded.t, "ledger_approval");
    assert.deepEqual(decoded.b, JSON.parse(JSON.stringify(BODY)));
  });

  it("python from_http decodes a multi-part body", () => {
    const big = { ...BODY, text: "x".repeat(5_000) };
    const h = toHttp("ledger_approval", big);
    assert.ok(h.parts.length > 1, `expected >1 part, got ${h.parts.length}`);
    for (const part of h.parts) {
      assert.match(part, /^B\$2J[0-9A-Z]{4}/);
      assert.ok(part.length <= 1000);
    }
    const decoded = pythonFromHttp(h);
    assert.deepEqual(decoded.b, JSON.parse(JSON.stringify(big)));
  });
});
