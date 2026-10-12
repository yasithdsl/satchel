import type { Page } from "@playwright/test";

const CORS = {
  "access-control-allow-origin": "*",
  "access-control-allow-methods": "GET, POST, OPTIONS",
  "access-control-allow-headers": "content-type",
};

export function sse(lines: Record<string, unknown>[]): string {
  return lines.map((l) => `data: ${JSON.stringify(l)}`).join("\n\n") + "\n\n";
}

export function xraySse(events: Record<string, unknown>[]): string {
  return (
    events
      .map((e) => `id: ${e.seq}\ndata: ${JSON.stringify(e)}`)
      .join("\n\n") + "\n\n"
  );
}

export interface MockOptions {
  chatBodies?: string[];
  orderStatus?: { current: string };
  xrayEvents?: string;
  xrayState?: Record<string, unknown>;
}

export async function mockBackends(page: Page, opts: MockOptions) {
  const posted: { url: string; body: unknown }[] = [];
  let chatIdx = 0;

  await page.route("**://127.0.0.1:8005/**", async (route) => {
    const req = route.request();
    if (req.method() === "OPTIONS") {
      return route.fulfill({ status: 204, headers: CORS });
    }
    const url = new URL(req.url());
    if (url.pathname === "/chat" && req.method() === "POST") {
      const bodies = opts.chatBodies ?? [];
      const body = bodies[Math.min(chatIdx++, Math.max(bodies.length - 1, 0))] ?? "";
      return route.fulfill({
        status: 200,
        headers: { ...CORS, "content-type": "text/event-stream" },
        body,
      });
    }
    if (url.pathname.startsWith("/orders/")) {
      return route.fulfill({
        status: 200,
        headers: { ...CORS, "content-type": "application/json" },
        body: JSON.stringify({
          status: opts.orderStatus?.current ?? "awaiting_payment",
        }),
      });
    }
    if (url.pathname === "/demo/compromise") {
      posted.push({ url: req.url(), body: req.postDataJSON() });
      return route.fulfill({
        status: 200,
        headers: { ...CORS, "content-type": "application/json" },
        body: JSON.stringify({
          drained_sats: 1234,
          envelope_balance_before: 5000,
          large_spend: {
            broadcast: false,
            stage: "approval",
            reason: "rejected",
          },
          sink: {},
        }),
      });
    }
    return route.fulfill({ status: 404, headers: CORS, body: "{}" });
  });

  await page.route("**://127.0.0.1:8006/**", async (route) => {
    const req = route.request();
    if (req.method() === "OPTIONS") {
      return route.fulfill({ status: 204, headers: CORS });
    }
    const url = new URL(req.url());
    if (url.pathname === "/events") {
      return route.fulfill({
        status: 200,
        headers: { ...CORS, "content-type": "text/event-stream" },
        body: opts.xrayEvents ?? "",
      });
    }
    if (url.pathname === "/state") {
      return route.fulfill({
        status: 200,
        headers: { ...CORS, "content-type": "application/json" },
        body: JSON.stringify(
          opts.xrayState ?? {
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
            loss_sink: null,
            random_nonce_signer: false,
            compromise_control: { enabled: true },
            pending_approval: { pending: null },
            errors: {},
          },
        ),
      });
    }
    if (url.pathname === "/demo/random-nonce") {
      posted.push({ url: req.url(), body: req.postDataJSON() });
      return route.fulfill({
        status: 200,
        headers: { ...CORS, "content-type": "application/json" },
        body: JSON.stringify({ enabled: req.postDataJSON().enabled }),
      });
    }
    if (url.pathname === "/demo/mine") {
      posted.push({ url: req.url(), body: null });
      return route.fulfill({
        status: 200,
        headers: { ...CORS, "content-type": "application/json" },
        body: JSON.stringify({ block_hash: "ab".repeat(32) }),
      });
    }
    return route.fulfill({ status: 404, headers: CORS, body: "{}" });
  });

  await page.route("**://127.0.0.1:5001/**", async (route) =>
    route.fulfill({
      status: 200,
      headers: { "content-type": "text/html" },
      body: "<html><body>Speculos</body></html>",
    }),
  );

  return { posted };
}
