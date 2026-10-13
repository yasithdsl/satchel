import assert from "node:assert/strict";
import { mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { after, describe, it } from "node:test";
import { createServer } from "../src/server.ts";
import { DeviceActionTimeout } from "../src/dmk.ts";
import { renderText, type Plan } from "../src/plan.ts";
import type { ApprovalDevice } from "../src/device.ts";
import { ReviewGone, type SpeculosDriver } from "../src/speculos.ts";
import type { Server } from "node:http";

const ADDR = { address: "0x1234567890abcdef1234567890abcdef12345678", path: "44'/60'/0'/0/0" };
const FUTURE = 4_102_444_800;

class FakeDevice implements ApprovalDevice {
  reject = false;
  fail: Error | null = null;
  delay = 0;
  timeout = false;
  async address() {
    return ADDR;
  }
  async signPersonalMessage(_text: string) {
    if (this.delay) await new Promise((r) => setTimeout(r, this.delay));
    if (this.timeout) throw new DeviceActionTimeout(1);
    if (this.reject) throw { _tag: "RefusedByUserDAError" };
    if (this.fail) throw this.fail;
    return { r: "0x" + "11".repeat(32), s: "0x" + "22".repeat(32), v: 27 };
  }
}

async function start(
  device: FakeDevice,
  opts: { demoAutomation?: boolean; demo?: SpeculosDriver | null } = {},
): Promise<{ base: string; server: Server }> {
  const server = createServer({ device, ...opts });
  await new Promise<void>((r) => server.listen(0, "127.0.0.1", r));
  const port = (server.address() as { port: number }).port;
  return { base: `http://127.0.0.1:${port}`, server };
}

const grant = (expires_at = FUTURE): Plan => ({
  kind: "satchel_grant",
  satchel_index: 0,
  psbt_sha256: "0".repeat(64),
  agent_id: "agent",
  budget_sats: 50_000,
  expires_at,
});

async function post(base: string, path: string, body: unknown) {
  return fetch(base + path, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
}

describe("approver server", () => {
  const device = new FakeDevice();
  let base: string;
  let server: Server;
  const log = join(mkdtempSync(join(tmpdir(), "satchel-")), "events.jsonl");
  process.env.SATCHEL_EVENT_LOG = log;

  it("setup", async () => {
    ({ base, server } = await start(device));
  });
  after(() => {
    server.closeIdleConnections();
    server.closeAllConnections();
    server.close();
  });

  it("GET /health", async () => {
    const res = await fetch(base + "/health");
    assert.deepEqual(await res.json(), { ok: true, demo_automation: false });
  });

  it("GET /address", async () => {
    const res = await fetch(base + "/address");
    assert.deepEqual(await res.json(), ADDR);
  });

  it("POST /approve returns a ledger_approval payload", async () => {
    const res = await post(base, "/approve", { plan: grant() });
    assert.equal(res.status, 200);
    const h = (await res.json()) as {
      type: string;
      payload: string;
      parts: string[];
    };
    assert.equal(h.type, "ledger_approval");
    const env = JSON.parse(h.payload) as { v: number; t: string; b: any };
    assert.equal(env.v, 1);
    const b = env.b;
    assert.deepEqual(Object.keys(b).sort(), [
      "address",
      "nonce",
      "path",
      "plan",
      "signature",
      "text",
    ]);
    assert.deepEqual(b.plan, grant());
    assert.match(b.nonce, /^[0-9a-f]{16}$/);
    assert.equal(b.text, renderText(b.plan, b.nonce));
    assert.match(b.signature, /^0x[0-9a-f]{130}$/);
    assert.equal(b.signature.slice(-2), "1b");
    assert.equal(b.address, ADDR.address);
    assert.equal(b.path, ADDR.path);
    assert.match(h.parts[0]!, /^B\$2J/);
  });

  it("nonces are unique", async () => {
    const n = new Set<string>();
    for (let i = 0; i < 3; i++) {
      const res = await post(base, "/approve", { plan: grant() });
      const h = (await res.json()) as { payload: string };
      n.add(JSON.parse(h.payload).b.nonce);
    }
    assert.equal(n.size, 3);
  });

  it("device rejection returns 409 with the rejection shape", async () => {
    device.reject = true;
    const res = await post(base, "/approve", { plan: grant() });
    device.reject = false;
    assert.equal(res.status, 409);
    const b = (await res.json()) as Record<string, unknown>;
    assert.equal(b.status, "rejected");
    assert.equal(b.reason, "Rejected on the Ledger");
    assert.match(b.nonce as string, /^[0-9a-f]{16}$/);
    assert.equal(b.text, renderText(grant(), b.nonce as string));
  });

  it("invalid plan returns 422", async () => {
    const res = await post(base, "/approve", { plan: { kind: "nope" } });
    assert.equal(res.status, 422);
  });

  it("expired grant returns 422", async () => {
    const res = await post(base, "/approve", { plan: grant(1_000) });
    assert.equal(res.status, 422);
  });

  it("malformed body returns 422", async () => {
    const res = await fetch(base + "/approve", {
      method: "POST",
      body: "not json",
    });
    assert.equal(res.status, 422);
  });

  it("demo_auto without automation returns 403", async () => {
    const res = await post(base, "/approve", { plan: grant(), demo_auto: "approve" });
    assert.equal(res.status, 403);
  });

  it("bad demo_auto value returns 422", async () => {
    const res = await post(base, "/approve", { plan: grant(), demo_auto: "yes" });
    assert.equal(res.status, 422);
  });

  it("demo routes are 404 when automation is off", async () => {
    assert.equal((await fetch(base + "/demo/screen")).status, 404);
    assert.equal((await fetch(base + "/demo/screenshot")).status, 404);
    assert.equal((await post(base, "/demo/approve", {})).status, 404);
    assert.equal((await post(base, "/demo/reject", {})).status, 404);
  });

  it("concurrent approvals return 409 device busy", async () => {
    device.delay = 300;
    const [a, b] = await Promise.all([
      post(base, "/approve", { plan: grant() }),
      post(base, "/approve", { plan: grant() }),
    ]);
    device.delay = 0;
    const codes = [a.status, b.status].sort();
    assert.deepEqual(codes, [200, 409]);
    const loser = a.status === 409 ? a : b;
    assert.deepEqual(await loser.json(), { detail: "device busy" });
  });

  it("GET /pending is null when idle", async () => {
    const res = await fetch(base + "/pending");
    assert.deepEqual(await res.json(), { pending: null });
  });

  it("GET /pending reports the in-flight approval then clears", async () => {
    device.delay = 300;
    const request = post(base, "/approve", { plan: grant() });
    try {
      let body: any = {};
      for (let i = 0; i < 30 && !body.pending; i++) {
        await new Promise((r) => setTimeout(r, 20));
        body = await (await fetch(base + "/pending")).json();
      }
      assert.ok(body.pending, "no pending approval reported");
      assert.equal(body.pending.kind, "satchel_grant");
      assert.equal(
        body.pending.text,
        renderText(grant(), body.pending.nonce),
      );
      assert.match(body.pending.nonce, /^[0-9a-f]{16}$/);
      assert.match(body.pending.started_at, /^\d{4}-\d{2}-\d{2}T\d{2}:/);
    } finally {
      device.delay = 0;
      await request;
    }
    const after = await fetch(base + "/pending");
    assert.deepEqual(await after.json(), { pending: null });
  });

  it("pending clears on rejection too", async () => {
    device.reject = true;
    const res = await post(base, "/approve", { plan: grant() });
    device.reject = false;
    assert.equal(res.status, 409);
    const after = await fetch(base + "/pending");
    assert.deepEqual(await after.json(), { pending: null });
  });

  it("timeout returns 504", async () => {
    device.timeout = true;
    const res = await post(base, "/approve", { plan: grant() });
    device.timeout = false;
    assert.equal(res.status, 504);
  });

  it("other device errors return 502", async () => {
    device.fail = new Error("kaboom");
    const res = await post(base, "/approve", { plan: grant() });
    device.fail = null;
    assert.equal(res.status, 502);
  });

  it("events were written", () => {
    const lines = readFileSync(log, "utf8")
      .trim()
      .split("\n")
      .map((l) => JSON.parse(l) as Record<string, any>);
    const types = new Set(lines.map((l) => l.type));
    for (const expected of [
      "approval_requested",
      "approval_granted",
      "approval_rejected",
      "approval_failed",
    ]) {
      assert.ok(types.has(expected), `missing ${expected}`);
    }
    for (const line of lines) {
      assert.equal(line.component, "approver");
      assert.ok(line.id && line.ts && line.message);
    }
  });
});

describe("demo_auto automation failures", () => {
  const device = new FakeDevice();
  let base: string;
  let server: Server;
  const failingDemo = {
    approveReview: () =>
      new Promise((_r, reject) =>
        setTimeout(() => reject(new Error("screen lost")), 20),
      ),
    rejectReview: () => Promise.reject(new Error("screen lost")),
    screen: async () => [],
    screenshot: async () => new Uint8Array(),
  } as unknown as SpeculosDriver;

  it("setup", async () => {
    ({ base, server } = await start(device, {
      demoAutomation: true,
      demo: failingDemo,
    }));
  });
  after(() => {
    server.closeIdleConnections();
    server.closeAllConnections();
    server.close();
  });

  it("waits for signing to settle, then returns 502", async () => {
    device.delay = 250;
    const started = Date.now();
    const res = await post(base, "/approve", {
      plan: grant(),
      demo_auto: "approve",
    });
    const elapsed = Date.now() - started;
    device.delay = 0;
    assert.equal(res.status, 502);
    const body = (await res.json()) as { detail: string };
    assert.match(body.detail, /demo automation failed: screen lost/);
    assert.ok(elapsed >= 200, `responded too early (${elapsed}ms)`);
  });

  it("device outcome wins when the automation also fails", async () => {
    device.reject = true;
    const res = await post(base, "/approve", {
      plan: grant(),
      demo_auto: "approve",
    });
    device.reject = false;
    assert.equal(res.status, 409);
  });

  it("the device is free again after an automation failure", async () => {
    const res = await post(base, "/approve", { plan: grant() });
    assert.equal(res.status, 200);
  });
});

describe("demo approve/reject buttons", () => {
  const device = new FakeDevice();
  let base: string;
  let server: Server;
  const calls: string[] = [];
  let release: (() => void) | null = null;
  let outcome: "ok" | "gone" = "ok";
  const demo = {
    approveReview: async (opts: { stillPending?: () => boolean } = {}) => {
      calls.push(`approve:${opts.stillPending?.() ?? "?"}`);
      await new Promise<void>((r) => (release = r));
      if (outcome === "gone") throw new ReviewGone();
    },
    rejectReview: async () => {
      calls.push("reject");
    },
    screen: async () => [],
    screenshot: async () => new Uint8Array(),
  } as unknown as SpeculosDriver;

  it("setup", async () => {
    ({ base, server } = await start(device, { demoAutomation: true, demo }));
  });
  after(() => {
    server.closeIdleConnections();
    server.closeAllConnections();
    server.close();
  });

  it("refuses with nothing_pending when no request is on the device", async () => {
    for (const path of ["/demo/approve", "/demo/reject"]) {
      const res = await post(base, path, {});
      assert.equal(res.status, 409, path);
      assert.equal(((await res.json()) as { reason: string }).reason, "nothing_pending");
    }
    assert.deepEqual(calls, [], "the emulator must not be touched");
  });

  async function waitPending() {
    for (let i = 0; i < 50; i++) {
      const body = (await (await fetch(base + "/pending")).json()) as { pending: unknown };
      if (body.pending) return;
      await new Promise((r) => setTimeout(r, 10));
    }
    throw new Error("approval never became pending");
  }

  it("drives the review while a request is pending, one press at a time", async () => {
    device.delay = 400;
    const approval = post(base, "/approve", { plan: grant() });
    await waitPending();
    const first = post(base, "/demo/approve", {});
    await new Promise((r) => setTimeout(r, 30));
    const second = await post(base, "/demo/approve", {});
    assert.equal(second.status, 409);
    assert.equal(((await second.json()) as { reason: string }).reason, "busy");
    release!();
    assert.equal((await first).status, 200);
    assert.deepEqual(calls, ["approve:true"]);
    assert.equal((await approval).status, 200);
    device.delay = 0;
  });

  it("a request decided mid-way is nothing_pending, not a 502", async () => {
    calls.length = 0;
    outcome = "gone";
    device.delay = 300;
    const approval = post(base, "/approve", { plan: grant() });
    await waitPending();
    const press = post(base, "/demo/approve", {});
    await new Promise((r) => setTimeout(r, 30));
    release!();
    const res = await press;
    assert.equal(res.status, 409);
    assert.equal(((await res.json()) as { reason: string }).reason, "nothing_pending");
    await approval;
    device.delay = 0;
    outcome = "ok";
  });
});
