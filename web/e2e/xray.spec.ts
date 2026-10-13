import { expect, test, type Page } from "@playwright/test";
import { mockBackends, sse, xraySse } from "./mocks.ts";

const GRANT = "Create a 0.002 BTC satchel #1 for shopper-3c483daf from main funds, expires 13 Oct 10:10 UTC. Nonce 157c097c898dbb12";
const FORBIDDEN = /bcrt1|\b[0-9a-f]{12,}\b|\bsats?\b|shopper-|nonce|\((4|5)\d\d\)/i;

let seq = 0;
function xev(extra: Record<string, unknown>): Record<string, unknown> {
  seq += 1;
  return {
    seq,
    id: `x${seq}`,
    ts: new Date().toISOString(),
    component: "laptop",
    type: "hop",
    message: "m",
    payload: null,
    boot: "boot-1",
    ...extra,
  };
}

function state(extra: Record<string, unknown> = {}) {
  return {
    ts: new Date().toISOString(),
    main_funds: {
      fingerprint: "f",
      addresses: 3,
      utxos: 3,
      balance_sats: 100_000_000,
      available_sats: 100_000_000,
    },
    envelopes: [
      {
        index: 1,
        budget_sats: 200_000,
        assigned_to: "agent-1",
        status: "assigned",
        balance_sats: 200_000,
        available_sats: 200_000,
      },
    ],
    loss_sink: { wallet: "loss-sink", confirmed_sats: 0, pending_sats: 0, last_address: null },
    random_nonce_signer: false,
    compromise_control: { enabled: true },
    pending_approval: { pending: null },
    errors: {},
    ...extra,
  };
}

const SESSION = sse([
  { type: "session", session_id: "s-x" },
  { type: "text", delta: "Hello." },
  { type: "done" },
]);

async function openXray(page: Page, query = "?autoplay=1") {
  await page.goto(`/${query}`);
  await page.getByLabel("Message").fill("hi");
  await page.getByRole("button", { name: "Send" }).click();
  await expect(page.getByText("Hello.")).toBeVisible();
  await page.getByRole("switch", { name: "X-ray" }).click();
  await expect(page.getByTestId("xray-panel")).toBeVisible();
}

async function fitsWithoutScrolling(page: Page) {
  return page
    .getByTestId("xray-panel")
    .evaluate((el) => el.scrollHeight <= el.clientHeight + 1);
}

for (const size of [
  { width: 1920, height: 1080 },
  { width: 1440, height: 900 },
]) {
  test(`x-ray takes two thirds and fits at ${size.width}x${size.height}`, async ({ page }) => {
    await page.setViewportSize(size);
    await mockBackends(page, { chatBodies: [SESSION], xrayState: state() });
    await openXray(page);
    await expect
      .poll(async () => (await page.getByTestId("xray-panel").boundingBox())?.width)
      .toBeCloseTo((size.width * 2) / 3, -1);
    await expect(page.getByTestId("chat-frame")).toBeVisible();
    await expect(page.getByTestId("caption-bar")).toBeVisible();
    await expect(page.getByTestId("device-strip")).toBeVisible();
    await expect(page.getByTestId("numbers-row")).toBeVisible();
    for (const zone of ["Online", "You", "Offline", "Network"]) {
      await expect(page.getByTestId("device-strip")).toContainText(zone, { ignoreCase: true });
    }
    await expect(page.getByTestId("strip-line-vault")).toHaveText("Holds the seed, sends no signatures");
    await expect(page.getByTestId("strip-line-ledger")).toHaveText("Nothing to approve");
    await expect(page.getByTestId("strip-node-attacker")).toHaveCount(0);
    await expect(page.getByTestId("number-main-funds-value")).toHaveText("$100,000");
    await expect(page.getByTestId("number-agent-budget")).toContainText("Agent's satchel");
    await expect(page.getByTestId("number-lost")).toHaveCount(0);
    await expect(page.getByTestId("details-drawer")).toHaveCount(0);
    expect(await fitsWithoutScrolling(page)).toBe(true);
  });
}

test("a presenter steps through the story with → and ←", async ({ page }) => {
  await page.setViewportSize({ width: 1920, height: 1080 });
  const { goLive } = await mockBackends(page, {
    chatBodies: [SESSION],
    xrayState: state(),
    xrayWaves: [[]],
    xrayLive: [
      xev({
        component: "agent",
        type: "tool_call",
        payload: { session_id: "s-x", agent_id: "agent-1", tool: "request_budget", input: { amount_usd: 200 } },
      }),
      xev({
        component: "vault",
        type: "satchel_reserved",
        payload: { envelope_index: 1, path: "m/84'/1'/0'/2'/1'", budget_sats: 200_000 },
      }),
      xev({ component: "vault", type: "verification_passed", payload: { reasons: [] } }),
    ],
  });
  await openXray(page, "");
  goLive();
  await expect(page.getByTestId("step-status")).toHaveText("3 more steps", { timeout: 15_000 });
  await expect(page.getByTestId("caption")).toHaveText("Waiting for your first request.");

  await page.keyboard.press("ArrowRight");
  const caption = page.getByTestId("caption");
  await expect(caption).toHaveText("Your agent asks for a $200 budget.");
  await expect(page.getByTestId("chapter")).toHaveText("Creating a satchel");
  await expect(page.getByTestId("chapter-step")).toHaveText(/Step 1 of 11/);
  await expect(page.getByTestId("caption-why")).toContainText("all it can do is ask");
  await expect(page.getByTestId("stage-panel")).toHaveAttribute("data-visual", "satchel");
  await expect(page.getByTestId("strip-node-agent")).toHaveAttribute("data-active", "true");
  await expect(page.getByTestId("strip-node-laptop")).toHaveAttribute("data-active", "true");
  await expect(page.getByTestId("strip-node-vault")).toHaveAttribute("data-dim", "true");

  await page.getByTestId("step-next").click();
  await expect(caption).toHaveText("The vault creates a fresh key for a new satchel.");
  await expect(page.getByTestId("caption-why")).toContainText("Fully hardened path m/84'/1'/0'/2'/1'.");
  await expect(page.getByTestId("satchel-path")).toHaveText("m/84'/1'/0'/2'/1'");

  await page.keyboard.press("ArrowRight");
  await expect(caption).toHaveText("The vault checks the signer's signature: it matches.");
  await expect(page.getByTestId("step-status")).toHaveText("Up to date");
  const earlier = page.getByTestId("caption-earlier");
  await expect(earlier).toHaveCount(2);
  await expect(page.getByTestId("strip-node-signer")).toHaveAttribute("data-active", "true");

  await page.keyboard.press("ArrowLeft");
  await expect(caption).toHaveText("The vault creates a fresh key for a new satchel.");
  await expect(page.getByTestId("step-status")).toHaveText("Reviewing an earlier step");
  await expect(page.getByTestId("strip-node-vault")).toHaveAttribute("data-active", "true");
  await page.keyboard.press("ArrowRight");
  await expect(caption).toHaveText("The vault checks the signer's signature: it matches.");
  expect(await page.locator("body").innerText()).not.toMatch(FORBIDDEN);
});

test("stepping back through history after a reload lights that step's devices", async ({ page }) => {
  await page.setViewportSize({ width: 1920, height: 1080 });
  const old = new Date(Date.now() - 5 * 60_000).toISOString();
  await mockBackends(page, {
    chatBodies: [SESSION],
    xrayState: state(),
    xrayWaves: [
      [
        xev({
          ts: old,
          component: "vault",
          type: "satchel_reserved",
          payload: { envelope_index: 0, path: "m/84'/1'/0'/2'/0'", budget_sats: 200_000 },
        }),
        xev({ ts: old, component: "vault", type: "verification_passed", payload: { reasons: [] } }),
      ],
    ],
  });
  await openXray(page);
  await expect(page.getByTestId("caption")).toHaveText(
    "The vault checks the signer's signature: it matches.",
  );
  await page.keyboard.press("ArrowLeft");
  await expect(page.getByTestId("caption")).toHaveText("The vault creates a fresh key for a new satchel.");
  await expect(page.getByTestId("strip-node-vault")).toHaveAttribute("data-active", "true");
  await expect(page.getByTestId("strip-node-agent")).toHaveAttribute("data-dim", "true");
});

test("an approval takes over the strip and never shows the idle screen", async ({ page }) => {
  await page.setViewportSize({ width: 1920, height: 1080 });
  const consoleLines: string[] = [];
  page.on("console", (m) => consoleLines.push(m.text()));
  const { posted, goLive } = await mockBackends(page, {
    chatBodies: [SESSION],
    xrayState: state(),
    xrayWaves: [[]],
    xrayLive: [
      xev({
        component: "approver",
        type: "approval_requested",
        payload: { kind: "satchel_grant", text: GRANT, nonce: "157c097c898dbb12" },
      }),
    ],
    ledgerTexts: ["Ethereum", "This app enables signing", "Quit app"],
    ledgerAction: {
      status: 502,
      body: { detail: { reason: "error", detail: "demo error: speculos /finger 500" } },
    },
  });
  await openXray(page);
  goLive();
  const takeover = page.getByTestId("ledger-takeover");
  await expect(takeover).toBeVisible({ timeout: 15_000 });
  await expect(page.getByTestId("device-strip")).toHaveCount(0);
  await expect(page.getByTestId("caption")).toHaveText(
    "Your laptop asks the Ledger to approve a $200 satchel.",
  );
  await expect(page.getByTestId("takeover-headline")).toHaveText(
    "Create a $200 satchel for your agent, funded from main funds.",
  );
  await expect(takeover).toContainText("Read it on the device, then approve or reject.");
  await expect(takeover).toContainText(
    "Emulated Ledger. Each approval is a signed message the vault verifies before releasing keys.",
  );
  // The device is still on the Ethereum home screen: show a calm placeholder.
  await expect(page.getByTestId("device-waiting")).toBeVisible();
  await expect(page.getByTestId("device-screen")).toHaveCount(0);
  await expect(page.getByTestId("device-approve")).toBeDisabled();
  expect(await fitsWithoutScrolling(page)).toBe(true);
  expect(await page.locator("body").innerText()).not.toMatch(FORBIDDEN);
  expect(posted.some((p) => p.url.includes("/ledger/approve"))).toBe(false);
  expect(consoleLines.join("\n")).not.toContain("502");
});

test("a device error is a calm retry; an already-decided request says nothing", async ({ page }) => {
  await page.setViewportSize({ width: 1920, height: 1080 });
  const consoleLines: string[] = [];
  page.on("console", (m) => consoleLines.push(m.text()));
  const action = { status: 502, body: { detail: { reason: "error", detail: "demo error: boom" } } as unknown };
  const { posted, goLive } = await mockBackends(page, {
    chatBodies: [SESSION],
    xrayState: state(),
    xrayWaves: [[]],
    xrayLive: [
      xev({
        component: "approver",
        type: "approval_requested",
        payload: { kind: "satchel_grant", text: GRANT, nonce: "n1" },
      }),
    ],
    ledgerTexts: ["Message", "Give your agent", "Reject", "2 of 3"],
    ledgerAction: action,
  });
  await openXray(page);
  goLive();
  await expect(page.getByTestId("device-screen")).toBeVisible({ timeout: 15_000 });
  await page.getByTestId("device-approve").click();
  await expect(page.getByTestId("ledger-trouble")).toHaveText("The Ledger didn't respond. Try again.");
  await expect(page.getByTestId("device-approve")).toBeEnabled();
  const text = await page.locator("body").innerText();
  expect(text).not.toMatch(/502|failed|boom/i);
  expect(consoleLines.some((l) => l.includes("approve returned 502"))).toBe(true);

  action.status = 409;
  action.body = { detail: { reason: "nothing_pending", detail: "already decided" } };
  await page.getByTestId("device-reject").click();
  await expect
    .poll(() => posted.filter((p) => p.url.includes("/ledger/reject")).length)
    .toBe(1);
  await expect(page.getByTestId("ledger-trouble")).toHaveCount(0);
});

test("details drawer opens on a node's latest payload; the log has no ids", async ({ page }) => {
  await page.setViewportSize({ width: 1920, height: 1080 });
  await mockBackends(page, {
    chatBodies: [SESSION],
    xrayState: state(),
    xrayWaves: [
      [
        xev({
          type: "key_release_received",
          message: "flow 77272e3c hop 4: vault -> laptop (key_release_received)",
          payload: { flow_id: "77272e3ce397455a9ca2ccaf5fc340ec", flow: "grant", from: "vault", to: "laptop", hop: 4 },
          label: "Vault → laptop: satchel key release (key hidden)",
          nodes: { from: "vault", to: "laptop" },
          qr: { type: "key_release", parts: ["B$:2J0100AApayload-one", "B$:2J0101AApayload-two"], redacted: true },
        }),
        xev({
          component: "vault",
          type: "satchel_released",
          message: "satchel 1 key released to shopper-3c483daf",
          payload: { envelope_index: 1, agent_id: "shopper-3c483daf", budget_sats: 200_000 },
        }),
      ],
    ],
  });
  await openXray(page);
  await expect(page.getByTestId("details-drawer")).toHaveCount(0);
  await page.getByTestId("strip-node-vault").first().click();
  const drawer = page.getByTestId("details-drawer");
  await expect(drawer).toBeVisible();
  await expect(drawer).toContainText("Vault: latest payload");
  await expect(page.getByTestId("qr-label")).toHaveText(
    "Vault → laptop: satchel key release (key hidden)",
  );
  await expect(drawer).toContainText("keys hidden");
  const drawn = await page
    .getByTestId("qr-canvas")
    .evaluate((c) => (c as HTMLCanvasElement).toDataURL().length);
  expect(drawn).toBeGreaterThan(1000);
  await expect(page.getByTestId("event-log")).toContainText("The vault hands over the satchel key.");
  expect(await drawer.innerText()).not.toMatch(FORBIDDEN);
  await page.getByTestId("details-node-network").click();
  await expect(drawer).toContainText("Nothing has crossed into or out of the bitcoin network yet.");
  await page.getByTestId("details-toggle").click();
  await expect(drawer).toHaveCount(0);
});

test("presenter drawer: hidden until P, then drives the scenes", async ({ page }) => {
  await page.setViewportSize({ width: 1920, height: 1080 });
  const { posted } = await mockBackends(page, {
    chatBodies: [SESSION],
    xrayState: state(),
  });
  await page.goto("/");
  await expect(page.getByTestId("presenter-drawer")).toHaveCount(0);
  await page.getByLabel("Message").press("p");
  await expect(page.getByTestId("presenter-drawer")).toHaveCount(0);
  await page.getByLabel("Message").fill("");
  await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur());
  await page.keyboard.press("p");
  const drawer = page.getByTestId("presenter-drawer");
  await expect(drawer).toBeVisible();
  for (const label of [
    "Reset demo",
    "Mine block",
    "Simulate compromised agent",
    "Random-nonce signer: off",
    "Steps: press → for each",
  ]) {
    await expect(drawer.getByRole("button", { name: label })).toBeVisible();
  }

  await page.getByTestId("scene-compromise").click();
  await expect
    .poll(() => posted.find((p) => p.url.endsWith("/chat"))?.body)
    .toEqual({ message: "Get me a $200 budget for today.", session_id: null });

  await page.getByTestId("presenter-mine").click();
  await expect.poll(() => posted.some((p) => p.url.includes("/demo/mine"))).toBe(true);

  await page.getByTestId("presenter-random-nonce").click();
  await expect
    .poll(() => posted.find((p) => p.url.includes("/demo/random-nonce"))?.body)
    .toEqual({ enabled: true });

  await expect(page.getByTestId("presenter-compromise")).toBeEnabled();
  await page.getByTestId("presenter-compromise").click();
  await expect
    .poll(() => posted.find((p) => p.url.includes("/demo/compromise"))?.body)
    .toEqual({ session_id: "s-x", request_sats: 5_000_000 });

  await page.keyboard.press("p");
  await expect(drawer).toHaveCount(0);
});

test("the compromise scene: attacker node, red banner, loss figure", async ({ page }) => {
  await page.setViewportSize({ width: 1920, height: 1080 });
  const { goLive } = await mockBackends(page, {
    chatBodies: [SESSION],
    xrayState: state({
      envelopes: [
        { index: 1, budget_sats: 200_000, assigned_to: "agent-1", status: "spent", balance_sats: 200_000, available_sats: 0 },
      ],
      loss_sink: { wallet: "loss-sink", confirmed_sats: 0, pending_sats: 199_859, last_address: null },
    }),
    xrayWaves: [
      [
        xev({
          component: "agent",
          type: "tool_call",
          ts: new Date(Date.now() - 120_000).toISOString(),
          payload: { session_id: "s-x", agent_id: "agent-1", tool: "check_budget", input: {} },
        }),
        xev({
          component: "agent",
          type: "wallet_loaded",
          ts: new Date(Date.now() - 120_000).toISOString(),
          payload: { envelope_index: 1, budget_sats: 200_000, agent_id: "agent-1" },
        }),
      ],
    ],
    xrayLive: [
      xev({ component: "agent", type: "compromise_started", payload: { agent_id: "agent-1" }, simulation: true }),
      xev({
        component: "agent",
        type: "payment_sent",
        payload: { envelope_index: 1, amount_sats: 199_859, change_sats: 0, to: "bcrt1qattacker000000000000" },
      }),
      xev({
        component: "agent",
        type: "compromise_envelope_drained",
        payload: { amount_sats: 199_859, envelope_balance_before: 200_000 },
        simulation: true,
      }),
    ],
  });
  await openXray(page);
  goLive();
  await expect(page.getByTestId("caption")).toHaveText(
    "Simulated attack: your agent is fully compromised.",
    { timeout: 15_000 },
  );
  await expect(page.getByTestId("attack-panel")).toBeVisible();
  await expect(page.getByTestId("simulation-chip")).toBeVisible();
  await expect(page.getByTestId("strip-node-attacker")).toBeVisible();
  const banner = page.getByTestId("moment-banner");
  await expect(banner).toHaveText(
    "Simulated attack: the agent is fully compromised. It lost its $200 satchel. Main funds untouched: $100,000.",
    { timeout: 15_000 },
  );
  await expect(page.getByTestId("number-lost-value")).toContainText("$200");
  await expect(page.getByTestId("number-agent-budget-value")).toContainText("$0");
  await expect(page.getByTestId("budget-pill")).toContainText("$0 of $200");
  expect(await fitsWithoutScrolling(page)).toBe(true);
  expect(await page.locator("body").innerText()).not.toMatch(FORBIDDEN);
  await expect(banner).toHaveCount(0, { timeout: 10_000 });
  await expect(page.getByTestId("moment-badge")).toHaveText("Simulated attack");
});
