import { expect, test, type Page } from "@playwright/test";
import { mockBackends, sse } from "./mocks.ts";

const PRODUCT = {
  id: "aurora-anc-wireless-headphones",
  name: "Aurora ANC Wireless Headphones",
  seller: "Aurora Audio",
  category: "headphones",
  price_usd: 179,
  price_btc: "0.00179",
  price_sats: 179_000,
  delivery_date: "2026-10-13",
  available: 12,
};

const FORBIDDEN = /bcrt1|\b[0-9a-f]{12,}\b|\bsats?\b|shopper-|\((4|5)\d\d\)/i;

async function send(page: Page, text: string) {
  await page.getByLabel("Message").fill(text);
  await page.getByRole("button", { name: "Send" }).click();
}

function stateWith(envelope: Record<string, unknown> | null) {
  return {
    ts: new Date().toISOString(),
    main_funds: {
      fingerprint: "f",
      addresses: 3,
      utxos: 3,
      balance_sats: 100_000_000,
      available_sats: 100_000_000,
    },
    envelopes: envelope ? [envelope] : [],
    loss_sink: null,
    random_nonce_signer: false,
    compromise_control: { enabled: true },
    pending_approval: { pending: null },
    errors: {},
  };
}

test.use({ viewport: { width: 1920, height: 1080 } });

test("shopper mode is one centred consumer column", async ({ page }) => {
  await mockBackends(page, { chatBodies: [] });
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Satchel" })).toBeVisible();
  await expect(page.getByText("Your personal shopper")).toBeVisible();
  await expect(page.getByTestId("budget-pill")).toHaveText("No budget yet");
  await expect(page.getByRole("switch", { name: "X-ray" })).toHaveAttribute(
    "aria-checked",
    "false",
  );
  const input = await page.getByLabel("Message").boundingBox();
  const header = await page.getByRole("heading", { name: "Satchel" }).boundingBox();
  // The column is about 720px wide and centred in a 1920px window.
  expect(header!.x).toBeGreaterThan(560);
  expect(input!.x + input!.width).toBeLessThan(1360);
  await expect(page.getByTestId("xray-panel")).toHaveCount(0);
  await expect(page.getByTestId("presenter-drawer")).toHaveCount(0);
});

test("suggestions are a row of up to three cards", async ({ page }) => {
  await mockBackends(page, {
    chatBodies: [
      sse([
        { type: "session", session_id: "s-cards" },
        { type: "tool_call", id: "t1", name: "search_products", input: { query: "headphones" } },
        {
          type: "tool_result",
          id: "t1",
          name: "search_products",
          result: { count: 1, results: [{ listing: PRODUCT }] },
        },
        { type: "tool_call", id: "t2", name: "suggest_products", input: { product_ids: [PRODUCT.id] } },
        {
          type: "tool_result",
          id: "t2",
          name: "suggest_products",
          result: {
            products: [1, 2, 3, 4].map((i) => ({ ...PRODUCT, id: `p${i}`, name: `${PRODUCT.name} ${i}` })),
          },
        },
        { type: "text", delta: "The **Aurora** pair is my pick." },
        { type: "done" },
      ]),
    ],
  });
  await page.goto("/");
  await page
    .getByRole("button", { name: "Find me headphones under $200 that arrive by Friday" })
    .click();
  const cards = page.getByTestId("product-card");
  await expect(cards).toHaveCount(3);
  await expect(cards.first()).toContainText("Aurora ANC Wireless Headphones 1");
  await expect(cards.first()).toContainText("$179");
  await expect(cards.first()).toContainText("0.00179 BTC");
  await expect(cards.first()).toContainText("Arrives Tue 13 Oct");
  await expect(cards.first().getByRole("button", { name: "Buy" })).toBeVisible();
  const boxes = await Promise.all([0, 1, 2].map((i) => cards.nth(i).boundingBox()));
  expect(boxes[0]!.y).toBe(boxes[2]!.y);
  await expect(page.getByText("The Aurora pair is my pick.")).toBeVisible();
});

test("a budget request is one Ledger row and the pill follows the budget", async ({ page }) => {
  const now = new Date().toISOString();
  await mockBackends(page, {
    chatBodies: [
      sse([
        { type: "session", session_id: "s-budget" },
        { type: "tool_call", id: "t1", name: "request_budget", input: { amount_usd: 200 } },
        {
          type: "tool_result",
          id: "t1",
          name: "request_budget",
          result: { granted: true, budget_sats: 200_000, budget_usd: 200, envelope_index: 0 },
        },
        { type: "text", delta: "Your $200 budget is ready." },
        { type: "done" },
      ]),
    ],
    xrayEvents: `id: 1\ndata: ${JSON.stringify({
      seq: 1,
      id: "e1",
      ts: now,
      component: "agent",
      type: "tool_call",
      message: "m",
      payload: { session_id: "s-budget", agent_id: "agent-1", tool: "request_budget", input: { amount_usd: 200 } },
      boot: "b",
    })}\n\n`,
    xrayState: stateWith({
      index: 0,
      budget_sats: 200_000,
      assigned_to: "agent-1",
      status: "assigned",
      balance_sats: 200_000,
      available_sats: 200_000,
    }),
  });
  await page.goto("/");
  await send(page, "Get me a $200 budget for today.");
  const row = page.getByTestId("approval-row");
  await expect(row).toHaveCount(1);
  await expect(row).toHaveText("Approved on Ledger: $200 budget");
  await expect(page.getByTestId("budget-pill")).toHaveText("Budget $200 of $200", {
    timeout: 10_000,
  });
});

test("an order card goes from Confirming to Paid", async ({ page }) => {
  const orderStatus = { current: "payment_pending" };
  await mockBackends(page, {
    orderStatus,
    chatBodies: [
      sse([
        { type: "session", session_id: "s-order" },
        { type: "tool_call", id: "b1", name: "buy_product", input: { product_id: PRODUCT.id } },
        {
          type: "tool_result",
          id: "b1",
          name: "buy_product",
          result: {
            status: "paid_from_budget",
            order_id: "a2e8f1ccb4724e4a86c8ad2a7e19b4ae",
            product: PRODUCT.name,
            amount_usd: 179,
            delivery_date: "2026-10-14",
            txid: "ab".repeat(32),
          },
        },
        { type: "text", delta: "Bought for $179. It's confirming now." },
        { type: "done" },
      ]),
    ],
  });
  await page.goto("/");
  await send(page, "Buy the Aurora ANC Wireless Headphones.");
  const card = page.getByTestId("order-card");
  await expect(card).toContainText(PRODUCT.name);
  await expect(card).toContainText("$179 · Arrives Wed 14 Oct");
  await expect(page.getByTestId("order-status")).toHaveText("Confirming");
  orderStatus.current = "paid";
  await expect(page.getByTestId("order-status")).toHaveText("Paid", { timeout: 10_000 });
  expect(await page.locator("body").innerText()).not.toMatch(FORBIDDEN);
});

test("a large purchase is a single Ledger row that changes when decided", async ({ page }) => {
  await mockBackends(page, {
    chatBodies: [
      sse([
        { type: "session", session_id: "s-big" },
        {
          type: "tool_call",
          id: "d1",
          name: "get_product_details",
          input: { product_id: "featherbook-13" },
        },
        {
          type: "tool_result",
          id: "d1",
          name: "get_product_details",
          result: {
            listing: { id: "featherbook-13", name: "Featherbook 13", category: "laptops", delivery_date: "2026-10-16" },
          },
        },
        { type: "tool_call", id: "b1", name: "buy_product", input: { product_id: "featherbook-13" } },
        {
          type: "tool_result",
          id: "b1",
          name: "buy_product",
          result: { status: "exceeds_budget", order_id: "o5", amount_usd: 799 },
        },
        { type: "tool_call", id: "t1", name: "request_large_purchase", input: { order_id: "o5" } },
        { type: "notice", text: "This purchase exceeds your prepaid budget and needs your approval on the Ledger" },
        { type: "done" },
      ]),
      sse([
        {
          type: "tool_result",
          id: "t1",
          name: "request_large_purchase",
          result: { paid: true, stage: "broadcast" },
        },
        { type: "text", delta: "Approved and paid." },
        { type: "done" },
      ]),
    ],
  });
  await page.goto("/");
  await send(page, "Buy me the Featherbook 13 laptop.");
  const row = page.getByTestId("approval-row");
  await expect(row).toHaveCount(1);
  await expect(row).toHaveText("Needs your approval on Ledger: $799 laptop from main funds");
  await expect(page.getByText(/exceeds your prepaid budget/)).toHaveCount(0);
  await send(page, "ok");
  await expect(row).toHaveText("Approved on Ledger: $799 laptop from main funds");
  await expect(page.getByTestId("order-card")).toContainText("Featherbook 13");
});

test("a failed request shows a calm retry, never the error", async ({ page }) => {
  const consoleLines: string[] = [];
  page.on("console", (m) => consoleLines.push(m.text()));
  const { posted } = await mockBackends(page, { chatStatus: 500 });
  await page.goto("/");
  await send(page, "Find me a kettle.");
  const retry = page.getByTestId("retry-row");
  await expect(retry).toContainText("That didn't go through.");
  expect(await page.locator("body").innerText()).not.toMatch(/500|chat failed/);
  expect(consoleLines.some((l) => l.includes("chat failed: 500"))).toBe(true);
  await retry.getByRole("button", { name: "Try again" }).click();
  await expect
    .poll(() => posted.filter((p) => p.url.endsWith("/chat")).length)
    .toBe(2);
  const bodies = posted.filter((p) => p.url.endsWith("/chat")).map((p) => p.body as { message: string });
  expect(bodies[1].message).toBe("Find me a kettle.");
});

test("chat never shows addresses or ids", async ({ page }) => {
  const addr = "bcrt1qxy2kgdygjrsqtzq2n0yrf2493p83kkfjhx0wlh";
  const hex = "ab".repeat(32);
  await mockBackends(page, {
    chatBodies: [
      sse([
        { type: "session", session_id: "s-mask" },
        {
          type: "text",
          delta: `I sent funds to ${addr} in tx ${hex}, order a2e8f1ccb4724e4a86c8ad2a7e19b4ae. All set!`,
        },
        { type: "done" },
      ]),
    ],
  });
  await page.goto("/");
  await send(page, "tell me");
  await expect(page.getByText(/All set!/)).toBeVisible();
  expect(await page.locator("body").innerText()).not.toMatch(FORBIDDEN);
});
