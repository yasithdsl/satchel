import { readdirSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { expect, test, type Page } from "@playwright/test";

const XRAY = "http://127.0.0.1:8006";
const SPECULOS = "http://127.0.0.1:5001";
const SHOT_DIR = "/tmp";

interface ScreenEvent {
  text: string;
  x: number;
  y: number;
  w: number;
  h: number;
}

async function screenEvents(): Promise<ScreenEvent[]> {
  const res = await fetch(`${SPECULOS}/events?currentscreenonly=true`);
  const body = (await res.json()) as { events?: ScreenEvent[] };
  return body.events ?? [];
}

async function screenTexts(): Promise<string[]> {
  return (await screenEvents()).map((e) => e.text);
}

async function xrayState(): Promise<Record<string, any>> {
  const res = await fetch(`${XRAY}/state`);
  return (await res.json()) as Record<string, any>;
}

function step(page: Page, id: string) {
  return page.getByTestId(`guide-step-${id}`);
}

async function waitDone(page: Page, id: string, timeout = 90_000) {
  await expect(step(page, id)).toHaveAttribute("data-done", "true", {
    timeout,
  });
}

async function waitDoneOr(page: Page, id: string, timeout: number) {
  try {
    await waitDone(page, id, timeout);
    return true;
  } catch {
    return false;
  }
}

async function sendChat(page: Page, text: string) {
  await page.getByPlaceholder("Ask for anything…").fill(text);
  await page.getByRole("button", { name: "Send", exact: true }).click();
  await expect(page.getByText(text, { exact: true })).toBeVisible({
    timeout: 60_000,
  });
}

async function shot(page: Page, name: string) {
  await page.screenshot({ path: `${SHOT_DIR}/satchel-demo-${name}.png` });
}

async function clickGuideAction(page: Page, id: string) {
  const action = page.getByTestId(`guide-action-${id}`);
  await expect(action).toBeVisible({ timeout: 30_000 });
  await action.click();
}

async function waitDeviceReview(page: Page, timeout = 90_000) {
  await expect(page.getByTestId("device-pending")).toBeVisible({
    timeout,
  });
}

async function waitScreenText(
  predicate: (texts: string[]) => boolean,
  timeout = 30_000,
): Promise<ScreenEvent[]> {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    const events = await screenEvents();
    if (predicate(events.map((e) => e.text))) return events;
    await new Promise((r) => setTimeout(r, 300));
  }
  throw new Error("screen never reached the expected state");
}

async function swipeLeft(page: Page) {
  const box = await page.getByTestId("device-screen").boundingBox();
  if (!box) throw new Error("device screen not visible");
  const y = box.y + box.height / 2;
  const x0 = box.x + box.width * 0.85;
  const x1 = box.x + box.width * 0.15;
  await page.mouse.move(x0, y);
  await page.mouse.down();
  await page.mouse.move(x1, y, { steps: 6 });
  await page.mouse.up();
}

async function holdToSign(page: Page) {
  const deadline = Date.now() + 45_000;
  let hold: ScreenEvent | undefined;
  while (Date.now() < deadline) {
    const events = await screenEvents();
    hold = events.find((e) => e.text.startsWith("Hold to"));
    if (hold) break;
    const texts = events.map((e) => e.text);
    if (texts.length === 0 || texts.includes("Ethereum")) {
      throw new Error("review left the device before hold control");
    }
    await swipeLeft(page);
    await new Promise((r) => setTimeout(r, 600));
  }
  if (!hold) throw new Error("hold-to-sign control never appeared");
  const box = await page.getByTestId("device-screen").boundingBox();
  if (!box) throw new Error("device screen not visible");
  const px = box.x + ((hold.x + hold.w / 2) / 480) * box.width;
  const py = box.y + ((hold.y + hold.h / 2) / 600) * box.height;
  await page.mouse.move(px, py);
  await page.mouse.down();
  await new Promise((r) => setTimeout(r, 5000));
  await page.mouse.up();
}

test.describe.configure({ mode: "serial" });

test("guided demo: purchase, compromise, malicious signer", async ({
  page,
}) => {
  test.setTimeout(600_000);
  const problems: string[] = [];
  page.on("console", (msg) => {
    if (msg.type() === "error" || msg.type() === "warning") {
      problems.push(`console ${msg.type()}: ${msg.text()}`);
    }
  });
  page.on("requestfailed", (req) => {
    if (req.url().includes("favicon")) return;
    const failure = req.failure()?.errorText ?? "";
    if (req.url().includes("/events") && failure === "net::ERR_ABORTED")
      return;
    problems.push(`request failed: ${req.url()} (${failure})`);
  });
  page.on("response", (res) => {
    if (res.url().includes("favicon")) return;
    if (res.status() >= 400) {
      problems.push(`${res.status()} ${res.url()}`);
    }
  });

  try {
  await page.goto("/");
  await page
    .getByRole("button", { name: "X-ray", exact: true })
    .click();
  await expect(page.getByTestId("xray-panel")).toBeVisible();
  await expect(page.getByTestId("device-screen")).toBeVisible({
    timeout: 15_000,
  });

  await page
    .getByRole("button", { name: "1 · Everyday purchase" })
    .click();
  await clickGuideAction(page, "ask");
  await waitDone(page, "ask");
  await waitDeviceReview(page);
  await shot(page, "1-ask");
  await page.getByTestId("device-approve").click();
  await waitDone(page, "approve-budget");
  await shot(page, "1-budget");
  await clickGuideAction(page, "buy");
  if (!(await waitDoneOr(page, "buy", 75_000))) {
    await sendChat(page, "Yes, please buy them.");
    await waitDone(page, "buy");
  }
  await shot(page, "1-buy");
  await clickGuideAction(page, "mine");
  await waitDone(page, "mine", 120_000);
  await expect(
    page.getByText("Paid", { exact: true }),
  ).toBeVisible({ timeout: 30_000 });
  await shot(page, "1-paid");

  await page
    .getByRole("button", { name: "2 · Compromised agent" })
    .click();
  await clickGuideAction(page, "mine-first");
  await waitDone(page, "mine-first", 60_000);
  await shot(page, "2-mine");
  await clickGuideAction(page, "compromise");
  await waitDone(page, "compromise", 120_000);
  const balances = page.getByTestId("balances");
  await expect(page.getByTestId("envelope-1-available")).toHaveText(
    "$0 / $200",
    { timeout: 15_000 },
  );
  await expect(balances).toContainText("pending block", {
    timeout: 15_000,
  });
  await expect(balances).toContainText(/Loss sink \(attacker\)\s*\$[1-9]/);
  await shot(page, "2-drained");
  await waitDeviceReview(page);
  await page.getByTestId("device-reject").click();
  await waitDone(page, "reject", 120_000);
  await shot(page, "2-rejected");
  await expect(page.getByTestId("guide-compromise-result")).toBeVisible({
    timeout: 30_000,
  });
  const afterCompromise = await xrayState();
  const sinkTotal =
    (afterCompromise.loss_sink?.confirmed_sats ?? 0) +
    (afterCompromise.loss_sink?.pending_sats ?? 0);
  expect(sinkTotal).toBeGreaterThan(0);
  expect(sinkTotal).toBeLessThanOrEqual(200_000);
  expect(afterCompromise.main_funds?.balance_sats).toBe(100_000_000);
  expect(afterCompromise.main_funds?.available_sats).toBe(100_000_000);
  await shot(page, "2-result");

  await page
    .getByRole("button", { name: "3 · Malicious signer" })
    .click();
  await clickGuideAction(page, "random-on");
  await waitDone(page, "random-on", 60_000);
  await shot(page, "3-random-on");
  await clickGuideAction(page, "ask-laptop");
  if (!(await waitDoneOr(page, "ask-laptop", 90_000))) {
    await sendChat(page, "Yes, go ahead.");
    await waitDone(page, "ask-laptop", 120_000);
  }
  await waitDeviceReview(page);
  await shot(page, "3-review");
  await holdToSign(page);
  await waitDone(page, "approve-spend", 120_000);
  await shot(page, "3-approved");
  await waitDone(page, "blocked", 120_000);
  await expect(page.getByTestId("xray-alert")).toBeVisible({
    timeout: 30_000,
  });
  await expect(
    page.getByTestId("xray-alert").getByText(
      "Vault blocked this transaction",
    ),
  ).toBeVisible();
  await shot(page, "3-blocked");
  await clickGuideAction(page, "random-off");
  await waitDone(page, "random-off", 60_000);
  await shot(page, "3-random-off");

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
