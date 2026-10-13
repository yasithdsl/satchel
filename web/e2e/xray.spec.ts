import { expect, test, type Page } from "@playwright/test";
import { mockBackends, sse, xraySse } from "./mocks.ts";

function xev(extra: Record<string, unknown>): Record<string, unknown> {
  return {
    id: "x",
    ts: new Date().toISOString(),
    component: "laptop",
    type: "hop",
    message: "m",
    payload: null,
    boot: "boot-1",
    ...extra,
  };
}

function watchConsole(page: Page): string[] {
  const messages: string[] = [];
  page.on("console", (msg) => {
    if (msg.type() === "error" || msg.type() === "warning") {
      messages.push(msg.text());
    }
  });
  return messages;
}

test("split screen, ledger device, story, guide, inspector", async ({
  page,
}) => {
  const consoleErrors = watchConsole(page);
  const { posted, goLive } = await mockBackends(page, {
    chatBodies: [
      sse([
        { type: "session", session_id: "s-x" },
        { type: "text", delta: "hi" },
        { type: "done" },
      ]),
    ],
    xrayWaves: [
      [
        xev({
          seq: 1,
          label: "Laptop → Ledger: plan for the human to approve",
          nodes: { from: "laptop", to: "ledger" },
        }),
        xev({
          seq: 2,
          component: "agent",
          type: "tool_call",
          label: "Agent: searching the shop",
          nodes: { from: "agent", to: "marketplace" },
          payload: {
            tool: "search_products",
            input: { query: "headphones" },
          },
        }),
        xev({
          seq: 3,
          label: "Vault → laptop: envelope key release (key hidden)",
          nodes: { from: "vault", to: "laptop" },
          qr: {
            type: "key_release",
            parts: ["B$:2J0100AApayload-one", "B$:2J0101AApayload-two"],
            redacted: true,
          },
        }),
        xev({
          seq: 4,
          component: "vault",
          type: "verification_failed",
          message: "vault verification failed",
          nodes: { at: "vault" },
          payload: { reasons: ["signature mismatch on input 0"] },
          alert: {
            level: "error",
            title: "Vault blocked this transaction",
            reasons: ["signature mismatch on input 0"],
          },
        }),
        xev({
          seq: 5,
          component: "agent",
          type: "compromise_started",
          message: "DEMO simulated compromise: agent session hijacked",
          nodes: { at: "agent" },
          simulation: true,
        }),
      ],
    ],
    xrayLive: [
      xev({
        seq: 6,
        component: "agent",
        type: "tool_call",
        nodes: { from: "agent", to: "laptop" },
        payload: {
          tool: "request_budget",
          input: { amount_usd: 200 },
        },
      }),
    ],
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
    ledgerTexts: ["Ethereum", "Quit app"],
  });

  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");
  await page.getByLabel("Message").fill("hi");
  await page.getByRole("button", { name: "Send" }).click();
  await expect(page.getByText("hi", { exact: true }).first()).toBeVisible();

  await page
    .getByRole("button", { name: "X-ray", exact: true })
    .click();
  const panel = page.getByTestId("xray-panel");
  await expect(panel).toBeVisible();

  await expect
    .poll(async () => (await page.locator("main").boundingBox())?.width)
    .toBeLessThan(650);
  const chatBox = await page.locator("main").boundingBox();
  const panelBox = await panel.boundingBox();
  expect(chatBox!.width).toBeGreaterThan(500);
  expect(panelBox!.width).toBeGreaterThan(780);

  const screen = page.getByTestId("device-screen");
  await expect(screen).toBeVisible({ timeout: 10_000 });
  await expect(page.getByTestId("device-pending")).toContainText(
    "Fund envelope 1",
  );
  await expect(page.getByTestId("device-hint")).toContainText(
    "Waiting for the request to reach the device",
  );

  const box = await screen.boundingBox();
  await page.mouse.click(
    box!.x + box!.width / 2,
    box!.y + box!.height / 2,
  );
  await expect
    .poll(() =>
      posted.some(
        (p) =>
          p.url.includes("/ledger/finger") &&
          (p.body as Record<string, unknown>).action ===
            "press-and-release",
      ),
    )
    .toBe(true);

  await page.getByTestId("device-approve").click();
  await expect
    .poll(() => posted.some((p) => p.url.includes("/ledger/approve")))
    .toBe(true);

  goLive();
  await expect(
    page.getByTestId("node-laptop"),
  ).toHaveAttribute("data-glow", "true", { timeout: 15_000 });
  await expect(page.getByTestId("hop-label")).toBeVisible();

  const story = page.getByTestId("story-feed");
  await expect(
    story.getByText("Agent searched the shop for “headphones”"),
  ).toBeVisible();
  await expect(
    story.getByText("Vault blocked the transaction: signature mismatch on input 0"),
  ).toBeVisible();
  await expect(
    story.getByText(
      "SIMULATION: an attacker has taken over the agent",
    ),
  ).toBeVisible();

  const canvas = page.getByTestId("qr-canvas");
  await expect(canvas).toBeVisible();
  const drawn = await canvas.evaluate(
    (c) => (c as HTMLCanvasElement).toDataURL().length,
  );
  expect(drawn).toBeGreaterThan(1000);
  await expect(
    page.getByTestId("payload-inspector").getByText("keys hidden"),
  ).toBeVisible();

  await expect(page.getByTestId("xray-alert")).toBeVisible();
  const alertBox = page.getByTestId("xray-alert");
  await expect(alertBox).toBeVisible();
  await expect(
    alertBox.getByText("Vault blocked this transaction"),
  ).toBeVisible();
  await expect(
    alertBox.getByText("signature mismatch on input 0"),
  ).toBeVisible();

  await page
    .getByRole("button", { name: "1 · Everyday purchase" })
    .click();
  await expect(page.getByTestId("guide-step-ask")).toHaveAttribute(
    "data-done",
    "true",
    { timeout: 15_000 },
  );
  await expect(
    page.getByTestId("guide-step-approve-budget"),
  ).toHaveAttribute("data-current", "true");

  expect(
    consoleErrors.filter((m) => m.includes("same key")),
  ).toEqual([]);
});

test("controls: random-nonce toggle and compromise button", async ({
  page,
}) => {
  const { posted } = await mockBackends(page, {
    chatBodies: [
      sse([
        { type: "session", session_id: "s-ctl" },
        { type: "text", delta: "hi" },
        { type: "done" },
      ]),
    ],
    xrayEvents: xraySse([
      xev({ seq: 1, component: "network", type: "block_mined" }),
    ]),
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

  await panel.getByText("Demo controls", { exact: true }).click();
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
});
