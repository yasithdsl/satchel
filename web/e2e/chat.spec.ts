import { expect, test } from "@playwright/test";
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

test("search then suggest_products renders product cards", async ({
  page,
}) => {
  await mockBackends(page, {
    chatBodies: [
      sse([
        { type: "session", session_id: "s-cards" },
        {
          type: "tool_call",
          id: "t1",
          name: "search_products",
          input: { query: "headphones" },
        },
        {
          type: "tool_result",
          id: "t1",
          name: "search_products",
          result: { count: 1, results: [{ id: PRODUCT.id }] },
        },
        {
          type: "tool_call",
          id: "t2",
          name: "suggest_products",
          input: { product_ids: [PRODUCT.id] },
        },
        {
          type: "tool_result",
          id: "t2",
          name: "suggest_products",
          result: { note: "n", products: [PRODUCT] },
        },
        { type: "text", delta: "The **Aurora** pair is my pick." },
        { type: "done" },
      ]),
    ],
  });

  await page.goto("/");
  await page
    .getByRole("button", {
      name: "Find me headphones under $200 that arrive by Friday",
    })
    .click();

  await expect(page.getByText("Aurora ANC Wireless Headphones")).toBeVisible();
  await expect(page.getByText("$179")).toBeVisible();
  await expect(page.getByText("0.00179 BTC")).toBeVisible();
  await expect(page.getByText("Arrives Tue 13 Oct")).toBeVisible();
  await expect(page.getByText("Sold by Aurora Audio")).toBeVisible();
  await expect(
    page.getByText("The Aurora pair is my pick."),
  ).toBeVisible();

  await page.screenshot({ path: "/tmp/satchel-ui-chat.png" });
});

test("large purchase shows notice, waiting status, then paid order chip", async ({
  page,
}) => {
  const orderStatus = { current: "awaiting_payment" };
  await mockBackends(page, {
    orderStatus,
    chatBodies: [
      sse([
        { type: "session", session_id: "s-big" },
        {
          type: "tool_call",
          id: "t1",
          name: "request_large_purchase",
          input: { order_id: "o5" },
        },
        {
          type: "notice",
          text: "This purchase exceeds your prepaid budget and needs your approval on the Ledger",
        },
        { type: "done" },
      ]),
      sse([
        {
          type: "tool_result",
          id: "t1",
          name: "request_large_purchase",
          result: { paid: true, stage: "broadcast" },
        },
        { type: "text", delta: "You approved it — order placed." },
        { type: "done" },
      ]),
    ],
  });

  await page.goto("/");
  await page.getByLabel("Message").fill("Buy me the Featherbook 13 laptop.");
  await page.getByRole("button", { name: "Send" }).click();

  const notice = page.getByText(
    "needs your approval on the Ledger",
  );
  const waiting = page.getByText("Waiting for your approval on Ledger");
  await expect(notice).toBeVisible();
  await expect(waiting).toBeVisible();
  const noticeBox = await notice.boundingBox();
  const waitBox = await waiting.boundingBox();
  expect(noticeBox!.y).toBeLessThan(waitBox!.y);

  await page.getByLabel("Message").fill("yes, approved");
  await page.getByRole("button", { name: "Send" }).click();

  const chip = page.getByText("Payment pending");
  await expect(chip).toBeVisible();

  orderStatus.current = "paid";
  await expect(page.getByText("Paid", { exact: true })).toBeVisible({
    timeout: 10_000,
  });
  await expect(page.getByText("Waiting for your approval on Ledger")).toHaveCount(
    0,
  );
});

test("chat never shows addresses or 64-hex strings", async ({ page }) => {
  const addr = "bcrt1qxy2kgdygjrsqtzq2n0yrf2493p83kkfjhx0wlh";
  const hex = "ab".repeat(32);
  await mockBackends(page, {
    chatBodies: [
      sse([
        { type: "session", session_id: "s-mask" },
        {
          type: "text",
          delta: `I sent funds to ${addr} in tx ${hex}. All set!`,
        },
        { type: "done" },
      ]),
    ],
  });

  await page.goto("/");
  await page.getByLabel("Message").fill("tell me");
  await page.getByRole("button", { name: "Send" }).click();

  await expect(page.getByText("All set!")).toBeVisible();
  await expect(page.getByText(addr)).toHaveCount(0);
  await expect(page.getByText(hex)).toHaveCount(0);
  await expect(page.getByText(/bcrt1/)).toHaveCount(0);
});
