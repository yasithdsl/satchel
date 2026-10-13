import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { verifyMessage } from "ethers";
import { createServer } from "../src/server.ts";
import { DmkApprovalDevice } from "../src/device.ts";
import { SpeculosDriver } from "../src/speculos.ts";
import type { Server } from "node:http";

const SPECULOS_URL = process.env.SPECULOS_URL ?? "http://127.0.0.1:5001";

async function speculosUp(): Promise<boolean> {
  try {
    const res = await fetch(`${SPECULOS_URL}/events?currentscreenonly=true`, {
      signal: AbortSignal.timeout(3_000),
    });
    return res.ok;
  } catch {
    return false;
  }
}

const up = await speculosUp();

const grant = {
  kind: "satchel_grant",
  satchel_index: 1,
  psbt_sha256: "0".repeat(64),
  agent_id: "shop",
  budget_sats: 50_000,
  expires_at: 4_102_444_800,
};

describe("speculos e2e", { skip: !up && "Speculos unreachable" }, () => {
  let server: Server;
  let base: string;
  const device = new DmkApprovalDevice(120_000);
  const demo = new SpeculosDriver(SPECULOS_URL);

  it("approve returns a signature that verifies on-chain style", async () => {
    server = createServer({ device, demo, demoAutomation: true });
    await new Promise<void>((r) => server.listen(0, "127.0.0.1", r));
    const port = (server.address() as { port: number }).port;
    base = `http://127.0.0.1:${port}`;

    const res = await fetch(base + "/approve", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ plan: grant, demo_auto: "approve" }),
    });
    assert.equal(res.status, 200);
    const h = (await res.json()) as { payload: string };
    const b = JSON.parse(h.payload).b;
    assert.equal(b.text.length > 0, true);
    assert.match(b.signature, /^0x[0-9a-f]{130}$/);
    assert.equal(verifyMessage(b.text, b.signature), b.address);
  });

  it("reject returns 409 rejected", async () => {
    const res = await fetch(base + "/approve", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ plan: grant, demo_auto: "reject" }),
    });
    assert.equal(res.status, 409);
    const b = (await res.json()) as Record<string, unknown>;
    assert.equal(b.status, "rejected");
    assert.equal(b.reason, "Rejected on the Ledger");
    server.closeIdleConnections();
    server.closeAllConnections();
    server.close();
    await device.close();
  });
});
