import { mkdirSync, readdirSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { expect, test, type Page } from "@playwright/test";

const XRAY = "http://127.0.0.1:8006";
const SHOT_DIR = resolve(process.cwd(), "../docs/screenshots");
const RUN_DIR = process.env.SATCHEL_SHOT_DIR ?? "/tmp";

/** Text that must never reach the audience in either view. */
const FORBIDDEN: [RegExp, string][] = [
  [/\bbc(rt)?1[a-z0-9]{6,}/i, "an address"],
  [/\b[0-9a-f]{12,}\b/i, "an id"],
  [/\bsats?\b/i, "a raw sats count"],
  [/shopper-|nonce|psbt|txid/i, "an internal identifier"],
  [/\((4|5)\d\d\)|\b(failed|error) \(?\d{3}/i, "an error code"],
  [/Traceback|Exception/, "a stack trace"],
];

async function xrayState(): Promise<Record<string, any>> {
  const res = await fetch(`${XRAY}/state`);
  return (await res.json()) as Record<string, any>;
}

async function checkAudienceView(page: Page, where: string) {
  const text = await page.locator("body").innerText();
  for (const [re, what] of FORBIDDEN) {
    const hit = re.exec(text);
    expect(hit, `${where}: shows ${what}: "${hit?.[0]}"`).toBeNull();
  }
  const xray = page.getByTestId("xray-panel");
  if (await xray.isVisible()) {
    const fits = await xray.evaluate((el) => el.scrollHeight <= el.clientHeight + 1);
    expect(fits, `${where}: the x-ray scrolls`).toBe(true);
  }
}

async function presenter(page: Page, testId: string) {
  const drawer = page.getByTestId("presenter-drawer");
  if (!(await drawer.isVisible())) await page.keyboard.press("p");
  await expect(drawer).toBeVisible();
  const button = page.getByTestId(testId);
  await expect(button).toBeEnabled({ timeout: 30_000 });
  await button.click();
  await page.keyboard.press("p");
  await expect(drawer).toBeHidden();
}

async function approveOnLedger(page: Page, decision: "approve" | "reject", shot?: string) {
  const takeover = page.getByTestId("ledger-takeover");
  await expect(takeover).toBeVisible({ timeout: 120_000 });
  await expect(page.getByTestId("device-screen")).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId(`device-${decision}`)).toBeEnabled();
  await page.waitForTimeout(1500);
  if (shot) await page.screenshot({ path: `${RUN_DIR}/satchel-demo-${shot}.png` });
  await checkAudienceView(page, `Ledger takeover (${shot ?? decision})`);
  await page.getByTestId(`device-${decision}`).click();
  await expect(takeover).toBeHidden({ timeout: 90_000 });
}

async function bigMoment(page: Page, kind: string, text: RegExp, file: string) {
  const banner = page.getByTestId("moment-banner");
  await expect(banner).toHaveAttribute("data-kind", kind, { timeout: 120_000 });
  await expect(banner).toContainText(text);
  await page.waitForTimeout(700);
  await page.screenshot({ path: `${SHOT_DIR}/${file}` });
  await checkAudienceView(page, `big moment ${kind}`);
  await expect(banner).toBeHidden({ timeout: 15_000 });
  await expect(page.getByTestId("moment-badge")).toHaveAttribute("data-kind", kind);
}

async function sendChat(page: Page, text: string) {
  await page.getByLabel("Message").fill(text);
  await page.getByRole("button", { name: "Send", exact: true }).click();
}

function figure(page: Page, id: string) {
  return page.getByTestId(`number-${id}-value`);
}

test("presenter drives all three scenes at 1920x1080", async ({ page }) => {
  test.setTimeout(900_000);
  mkdirSync(SHOT_DIR, { recursive: true });
  const problems: string[] = [];
  page.on("console", (msg) => {
    if (msg.type() === "error" || msg.type() === "warning") {
      problems.push(`console ${msg.type()}: ${msg.text()}`);
    }
  });
  page.on("requestfailed", (req) => {
    if (req.url().includes("favicon")) return;
    const failure = req.failure()?.errorText ?? "";
    if (failure === "net::ERR_ABORTED") return;
    problems.push(`request failed: ${req.url()} (${failure})`);
  });
  page.on("response", (res) => {
    if (res.url().includes("favicon")) return;
    if (res.status() >= 400) problems.push(`${res.status()} ${res.url()}`);
  });

  const start = await xrayState();
  expect(start.main_funds?.available_sats, "run demo_reset.py first").toBe(100_000_000);
  expect((start.envelopes ?? []).map((e: any) => e.budget_sats)).toEqual([
    200_000, 200_000, 100_000,
  ]);

  try {
    await page.goto("/");
    await expect(page.getByTestId("budget-pill")).toHaveText("No budget yet");
    await page.getByRole("switch", { name: "X-ray" }).click();
    await expect(page.getByTestId("xray-panel")).toBeVisible();
    await expect(page.getByTestId("ledger-device")).toHaveCount(0);
    await expect(page.getByTestId("strip-line-ledger")).toHaveText("Nothing to approve");
    await checkAudienceView(page, "start");

    // Scene 1: an everyday purchase inside a $200 budget.
    await presenter(page, "scene-purchase");
    await approveOnLedger(page, "approve", "1-budget");
    await expect(page.getByTestId("budget-pill")).toContainText("$200 of $200", {
      timeout: 60_000,
    });
    const aurora = page.getByTestId("product-card").filter({ hasText: "Aurora" });
    await expect(aurora).toBeVisible({ timeout: 120_000 });
    await expect(aurora.getByRole("button", { name: "Buy" })).toBeEnabled({ timeout: 60_000 });
    await aurora.getByRole("button", { name: "Buy" }).click();
    try {
      await expect(page.getByTestId("order-card")).toBeVisible({ timeout: 90_000 });
    } catch {
      await sendChat(page, "Yes, please buy them.");
      await expect(page.getByTestId("order-card")).toBeVisible({ timeout: 90_000 });
    }
    await bigMoment(
      page,
      "purchase",
      /Paid from the \$200 budget\. No Ledger tap needed\./,
      "scene-1-paid-from-budget.png",
    );
    await expect(page.getByTestId("order-status")).toHaveText("Confirming");
    await presenter(page, "presenter-mine");
    await expect(page.getByTestId("order-status")).toHaveText("Paid", { timeout: 60_000 });
    await expect(page.getByTestId("budget-pill")).toContainText("$21 of $200");
    await expect(figure(page, "agent-budget")).toContainText("$21");
    await checkAudienceView(page, "scene 1 done");

    // Scene 2: a fresh $200 budget, then a fully compromised agent.
    await presenter(page, "scene-compromise");
    await approveOnLedger(page, "approve", "2-budget");
    await expect(page.getByTestId("budget-pill")).toContainText("$200 of $200", {
      timeout: 60_000,
    });
    await expect(page.getByTestId("number-lost")).toHaveCount(0);
    await presenter(page, "presenter-compromise");
    await expect(page.getByTestId("strip-node-attacker")).toBeVisible({ timeout: 60_000 });
    await bigMoment(
      page,
      "compromise",
      /Simulated attack: the agent is fully compromised\. It lost its \$200 budget\. Main funds untouched: \$100,000\./,
      "scene-2-simulated-attack.png",
    );
    await expect(figure(page, "lost")).toHaveText(/\$(199|200)/);
    await expect(figure(page, "agent-budget")).toContainText("$0");
    await expect(page.getByTestId("budget-pill")).toContainText("$0 of $200");
    await approveOnLedger(page, "reject", "2-attack-request");
    await expect(page.getByTestId("caption")).toHaveText(
      "Request for $5,000 more: rejected on your Ledger.",
      { timeout: 30_000 },
    );
    await page.waitForTimeout(800);
    await page.screenshot({ path: `${SHOT_DIR}/scene-2-request-rejected.png` });
    await expect(figure(page, "main-funds")).toHaveText("$100,000");
    await checkAudienceView(page, "scene 2 done");
    const afterAttack = await xrayState();
    expect(afterAttack.main_funds?.available_sats).toBe(100_000_000);

    // Scene 3: a cheating signer, caught by the vault.
    await presenter(page, "presenter-random-nonce");
    await expect(page.getByTestId("strip-line-signer")).toHaveText("Set to cheat (demo)", {
      timeout: 30_000,
    });
    await presenter(page, "scene-signer");
    await approveOnLedger(page, "approve", "3-budget");
    await expect(page.getByTestId("budget-pill")).toContainText("$100 of $100", {
      timeout: 60_000,
    });
    await expect(page.getByTestId("strip-node-attacker")).toHaveCount(0);
    await presenter(page, "scene-signer-then-0");
    await expect(
      page.getByTestId("approval-row").filter({ hasText: "from main funds" }),
    ).toBeVisible({ timeout: 120_000 });
    await approveOnLedger(page, "approve", "3-laptop");
    await bigMoment(
      page,
      "blocked",
      /Vault blocked the transaction: the signer's signature didn't match\. Nothing was sent\./,
      "scene-3-vault-blocked.png",
    );
    await expect(
      page.getByTestId("approval-row").filter({ hasText: "Blocked by your vault" }),
    ).toBeVisible({ timeout: 60_000 });
    await expect(figure(page, "main-funds")).toHaveText("$100,000");
    await presenter(page, "presenter-random-nonce");
    await expect(page.getByTestId("strip-line-signer")).toHaveText("Signs with one-time keys", {
      timeout: 30_000,
    });
    await checkAudienceView(page, "scene 3 done");

    const final = await xrayState();
    expect(final.main_funds?.available_sats).toBe(100_000_000);
    const logDir = resolve(process.cwd(), "../.satchel/logs");
    for (const f of readdirSync(logDir).filter((f) => f.endsWith(".log"))) {
      for (const line of readFileSync(`${logDir}/${f}`, "utf8").split("\n")) {
        if (line.includes("Traceback") || line.includes(" 500 ")) {
          problems.push(`log ${f}: ${line.trim().slice(0, 160)}`);
        }
      }
    }
  } finally {
    console.log("problems:", JSON.stringify(problems, null, 1));
  }
  expect(problems).toEqual([]);
});
