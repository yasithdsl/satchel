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
  const fits = await page
    .getByTestId("xray-panel")
    .evaluate((el) => el.scrollHeight <= el.clientHeight + 1);
  expect(fits, `${where}: the x-ray scrolls`).toBe(true);
}

async function presenter(page: Page, testId: string) {
  const drawer = page.getByTestId("presenter-drawer");
  if (!(await drawer.isVisible())) await page.keyboard.press("p");
  await expect(drawer).toBeVisible();
  const button = page.getByTestId(testId);
  await expect(button).toBeEnabled({ timeout: 60_000 });
  await button.click();
  await page.keyboard.press("p");
  await expect(drawer).toBeHidden();
}

/** Press → like a presenter until `ready` holds. */
async function stepUntil(page: Page, ready: () => Promise<boolean>, what: string, timeout = 180_000) {
  const deadline = Date.now() + timeout;
  const next = page.getByTestId("step-next");
  while (Date.now() < deadline) {
    if (await ready()) return;
    if (await next.isEnabled()) {
      await page.keyboard.press("ArrowRight");
      await page.waitForTimeout(250);
    } else {
      await page.waitForTimeout(300);
    }
  }
  throw new Error(`never reached: ${what}`);
}

function caption(page: Page) {
  return page.getByTestId("caption");
}

async function stepToCaption(page: Page, text: string | RegExp) {
  await stepUntil(
    page,
    async () => {
      const shown = (await caption(page).textContent()) ?? "";
      return typeof text === "string" ? shown === text : text.test(shown);
    },
    `caption ${text}`,
  );
}

async function ledger(page: Page, decision: "approve" | "reject", shot: string) {
  await stepUntil(page, () => page.getByTestId("ledger-takeover").isVisible(), "the Ledger takeover");
  await expect(page.getByTestId("device-screen")).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId(`device-${decision}`)).toBeEnabled();
  await page.waitForTimeout(1200);
  await page.screenshot({ path: `${RUN_DIR}/satchel-pitch-${shot}.png` });
  await checkAudienceView(page, `Ledger (${shot})`);
  await page.getByTestId(`device-${decision}`).click();
  await expect(page.getByTestId("ledger-takeover")).toBeHidden({ timeout: 120_000 });
}

async function bigMoment(page: Page, kind: string, text: RegExp, file: string) {
  await stepUntil(
    page,
    async () => (await page.getByTestId("moment-banner").getAttribute("data-kind").catch(() => null)) === kind,
    `the ${kind} moment`,
  );
  await expect(page.getByTestId("moment-banner")).toContainText(text);
  await page.waitForTimeout(700);
  await page.screenshot({ path: `${SHOT_DIR}/${file}` });
  await checkAudienceView(page, `big moment ${kind}`);
}

function figure(page: Page, id: string) {
  return page.getByTestId(`number-${id}-value`);
}

async function satchelCreated(page: Page, usd: string, shot: string) {
  await ledger(page, "approve", `${shot}-ledger`);
  await stepToCaption(page, `Your agent now holds a ${usd} satchel.`);
  await expect(page.getByTestId("satchel-checklist").locator("[data-done]")).toHaveCount(9);
  await expect(page.getByTestId("chapter-step")).toHaveText(/Step 11 of 11/);
  await page.screenshot({ path: `${RUN_DIR}/satchel-pitch-${shot}-created.png` });
  await checkAudienceView(page, `${shot} satchel created`);
}

test("a presenter walks all three scenes at 1920x1080", async ({ page }) => {
  test.setTimeout(1_200_000);
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
  expect(start.envelopes ?? [], "satchels are created on request").toEqual([]);

  try {
    await page.goto("/");
    await expect(page.getByTestId("budget-pill")).toHaveText("No budget yet");
    await page.getByRole("switch", { name: "X-ray" }).click();
    await expect(page.getByTestId("xray-panel")).toBeVisible();
    await expect(page.getByTestId("strip-line-ledger")).toHaveText("Nothing to approve");
    await checkAudienceView(page, "start");

    // Scene 1: one Ledger tap creates a $200 satchel; the agent shops inside it.
    await presenter(page, "scene-purchase");
    await stepToCaption(page, "Your agent asks for a $200 budget.");
    await expect(page.getByTestId("chapter")).toHaveText("Creating a satchel");
    await satchelCreated(page, "$200", "1");
    await expect(figure(page, "main-funds")).toHaveText("$99,800");
    const aurora = page.getByTestId("product-card").filter({ hasText: "Aurora" });
    await expect(aurora.getByRole("button", { name: "Buy" })).toBeEnabled({ timeout: 120_000 });
    await stepUntil(page, () => page.getByTestId("store-panel").isVisible(), "the store");
    await aurora.getByRole("button", { name: "Buy" }).click();
    await bigMoment(
      page,
      "purchase",
      /Paid from the \$200 satchel\. No Ledger tap needed\./,
      "scene-1-paid-from-satchel.png",
    );
    await expect(page.getByTestId("store-paid")).toBeVisible();
    await presenter(page, "presenter-mine");
    await stepToCaption(page, "The payment confirmed. Your order is paid.");
    await expect(page.getByTestId("order-status")).toHaveText("Paid", { timeout: 60_000 });
    await expect(page.getByTestId("budget-pill")).toContainText("$21 of $200");
    await expect(figure(page, "agent-budget")).toContainText("$21");
    await checkAudienceView(page, "scene 1 done");

    // Scene 2: a fresh $200 satchel, then a fully compromised agent.
    await presenter(page, "scene-compromise");
    await satchelCreated(page, "$200", "2");
    const mainBefore = await figure(page, "main-funds").textContent();
    await expect(page.getByTestId("number-lost")).toHaveCount(0);
    await presenter(page, "presenter-compromise");
    await stepToCaption(page, "Simulated attack: your agent is fully compromised.");
    await expect(page.getByTestId("attack-panel")).toBeVisible();
    await page.screenshot({ path: `${RUN_DIR}/satchel-pitch-2-attack.png` });
    await bigMoment(
      page,
      "compromise",
      /Simulated attack: the agent is fully compromised\. It lost its \$200 satchel\. Main funds untouched: \$99,\d{3}\./,
      "scene-2-simulated-attack.png",
    );
    await expect(figure(page, "lost")).toHaveText(/\$(199|200)/);
    await ledger(page, "reject", "2-attack-request");
    await stepToCaption(page, "Request for $5,000 more: rejected on your Ledger.");
    await expect(page.getByTestId("attack-request")).toHaveAttribute("data-outcome", "rejected");
    await page.waitForTimeout(800);
    await page.screenshot({ path: `${SHOT_DIR}/scene-2-request-rejected.png` });
    await expect(figure(page, "main-funds")).toHaveText(mainBefore ?? "");
    await checkAudienceView(page, "scene 2 done");

    // Scene 3: a $100 satchel, then a rigged signer caught by the vault.
    await presenter(page, "scene-signer");
    await satchelCreated(page, "$100", "3");
    await presenter(page, "presenter-random-nonce");
    await stepToCaption(page, "Simulated attack: the signer is rigged.");
    await expect(page.getByTestId("signer-panel")).toBeVisible();
    await page.screenshot({ path: `${RUN_DIR}/satchel-pitch-3-signer.png` });
    await presenter(page, "scene-signer-then-0");
    await ledger(page, "approve", "3-laptop");
    await bigMoment(
      page,
      "blocked",
      /Vault blocked the transaction: the signer's signature didn't match\. Nothing was sent\./,
      "scene-3-vault-blocked.png",
    );
    await expect(page.getByTestId("signature-check")).toHaveAttribute("data-verdict", "forged");
    await expect(
      page.getByTestId("approval-row").filter({ hasText: "Blocked by your vault" }),
    ).toBeVisible({ timeout: 60_000 });
    await presenter(page, "presenter-random-nonce");
    await stepToCaption(page, "Demo: the signer is honest again.");
    await checkAudienceView(page, "scene 3 done");

    const final = await xrayState();
    const logDir = resolve(process.cwd(), "../.satchel/logs");
    for (const f of readdirSync(logDir).filter((f) => f.endsWith(".log"))) {
      for (const line of readFileSync(`${logDir}/${f}`, "utf8").split("\n")) {
        if (line.includes("Traceback") || line.includes(" 500 ")) {
          problems.push(`log ${f}: ${line.trim().slice(0, 160)}`);
        }
      }
    }
    expect(final.main_funds?.balance_sats).toBeGreaterThan(99_000_000);
  } finally {
    console.log("problems:", JSON.stringify(problems, null, 1));
  }
  expect(problems).toEqual([]);
});
