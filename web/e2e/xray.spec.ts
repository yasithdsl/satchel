import { expect, test } from "@playwright/test";
import { mockBackends, sse, xraySse } from "./mocks.ts";

function xev(extra: Record<string, unknown>): Record<string, unknown> {
  return {
    id: "x",
    ts: new Date().toISOString(),
    component: "laptop",
    type: "hop",
    message: "m",
    payload: null,
    ...extra,
  };
}

test("x-ray panel: diagram, QR, alerts, simulation, controls", async ({
  page,
}) => {
  const { posted } = await mockBackends(page, {
    chatBodies: [
      sse([
        { type: "session", session_id: "s-x" },
        { type: "text", delta: "hi" },
        { type: "done" },
      ]),
    ],
    xrayEvents: xraySse([
      xev({
        seq: 1,
        label: "Laptop → Ledger: plan for the human to approve",
        nodes: { from: "laptop", to: "ledger" },
      }),
      xev({
        seq: 2,
        label: "Vault → laptop: envelope key release (key hidden)",
        nodes: { from: "vault", to: "laptop" },
        qr: {
          type: "key_release",
          parts: ["B$:2J0100AApayload-one", "B$:2J0101AApayload-two"],
          redacted: true,
        },
      }),
      xev({
        seq: 3,
        component: "vault",
        type: "verification_failed",
        message: "vault verification failed",
        nodes: { at: "vault" },
        alert: {
          level: "error",
          title: "Vault blocked this transaction",
          reasons: ["signature mismatch on input 0"],
        },
      }),
      xev({
        seq: 4,
        component: "agent",
        type: "compromise_started",
        message: "DEMO simulated compromise: agent session hijacked",
        nodes: { at: "agent" },
        simulation: true,
      }),
    ]),
    xrayState: {
      ts: new Date().toISOString(),
      main_funds: {
        fingerprint: "abcd1234",
        addresses: 5,
        utxos: 2,
        balance_sats: 4_000_000,
        available_sats: 4_000_000,
      },
      envelopes: [
        {
          index: 1,
          budget_sats: 200_000,
          assigned_to: "shopper-1",
          status: "active",
          balance_sats: 21_000,
        },
      ],
      loss_sink: {
        wallet: "attacker",
        confirmed_sats: 5_000,
        pending_sats: 0,
        last_address: null,
      },
      random_nonce_signer: false,
      compromise_control: { enabled: true },
      pending_approval: {
        pending: {
          kind: "envelope_release",
          text: "Fund envelope 1 for shopper-1 with 200000 sats",
          nonce: "n",
          started_at: new Date().toISOString(),
        },
      },
      errors: {},
    },
  });

  await page.goto("/");
  await page.getByLabel("Message").fill("hi");
  await page.getByRole("button", { name: "Send" }).click();
  await expect(page.getByText("hi", { exact: true }).first()).toBeVisible();

  await page
    .getByRole("button", { name: "X-ray", exact: true })
    .click();
  const panel = page.getByTestId("xray-panel");
  await expect(panel).toBeVisible();

  await expect(page.getByTestId("node-ledger")).toHaveAttribute(
    "data-glow",
    "true",
    { timeout: 5_000 },
  );

  const canvas = page.getByTestId("qr-canvas");
  await expect(canvas).toBeVisible();
  const drawn = await canvas.evaluate(
    (c) => (c as HTMLCanvasElement).toDataURL().length,
  );
  expect(drawn).toBeGreaterThan(1000);
  await expect(
    panel.getByText("Vault → laptop: envelope key release (key hidden)").first(),
  ).toBeVisible();
  await expect(panel.getByText("keys hidden")).toBeVisible();
  await expect(panel.getByText("part", { exact: false })).toBeVisible();

  await expect(page.getByTestId("xray-alert")).toBeVisible();
  await expect(
    page.getByText("Vault blocked this transaction"),
  ).toBeVisible();
  await expect(
    page.getByText("signature mismatch on input 0"),
  ).toBeVisible();

  await expect(
    page.getByText("SIMULATION", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("DEMO simulated compromise: agent session hijacked"),
  ).toBeVisible();

  await expect(
    page.getByText("Fund envelope 1 for shopper-1 with 200000 sats"),
  ).toBeVisible();

  await page.getByTestId("random-nonce-toggle").click();
  await expect
    .poll(() => posted.some((p) => p.url.includes("/demo/random-nonce")))
    .toBe(true);
  const rn = posted.find((p) => p.url.includes("/demo/random-nonce"));
  expect(rn?.body).toEqual({ enabled: true });

  await page.getByTestId("compromise-button").click();
  await expect(page.getByTestId("compromise-result")).toBeVisible();
  await expect
    .poll(() => posted.some((p) => p.url.includes("/demo/compromise")))
    .toBe(true);

  await panel
    .locator(":scope > .overflow-y-auto")
    .evaluate((el) => (el.scrollTop = 0));
  await page.screenshot({ path: "/tmp/satchel-ui-xray.png", fullPage: true });
});
