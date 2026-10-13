import type { Page } from "@playwright/test";

const CORS = {
  "access-control-allow-origin": "*",
  "access-control-allow-methods": "GET, POST, OPTIONS",
  "access-control-allow-headers": "content-type, last-event-id",
};

export const PNG_1PX = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
  "base64",
);

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
  xrayWaves?: Record<string, unknown>[][];
  xrayLive?: Record<string, unknown>[];
  xrayState?: Record<string, unknown>;
  ledgerTexts?: string[];
  automation?: boolean;
}

export async function mockBackends(page: Page, opts: MockOptions) {
  const posted: { url: string; body: unknown }[] = [];
  let chatIdx = 0;
  let waveIdx = 0;
  let live = false;

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
      let body = opts.xrayEvents ?? "";
      if (opts.xrayWaves) {
        const lastId = Number(req.headers()["last-event-id"] ?? 0);
        const wave =
          opts.xrayWaves[
            Math.min(waveIdx, opts.xrayWaves.length - 1)
          ];
        waveIdx += 1;
        body = xraySse(wave.filter((e) => Number(e.seq) > lastId));
      }
      if (opts.xrayLive && live) {
        const lastId = Number(req.headers()["last-event-id"] ?? 0);
        body += xraySse(
          opts.xrayLive.filter((e) => Number(e.seq) > lastId),
        );
      }
      return route.fulfill({
        status: 200,
        headers: { ...CORS, "content-type": "text/event-stream" },
        body,
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
                available_sats: 18_000,
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
    if (url.pathname === "/ledger/screenshot") {
      return route.fulfill({
        status: 200,
        headers: { ...CORS, "content-type": "image/png" },
        body: PNG_1PX,
      });
    }
    if (url.pathname === "/ledger/screen-text") {
      return route.fulfill({
        status: 200,
        headers: { ...CORS, "content-type": "application/json" },
        body: JSON.stringify({
          texts: opts.ledgerTexts ?? ["Ethereum", "Quit app"],
        }),
      });
    }
    if (url.pathname === "/ledger/finger" && req.method() === "POST") {
      posted.push({ url: req.url(), body: req.postDataJSON() });
      return route.fulfill({
        status: 200,
        headers: { ...CORS, "content-type": "application/json" },
        body: "{}",
      });
    }
    if (url.pathname === "/ledger/automation") {
      return route.fulfill({
        status: 200,
        headers: { ...CORS, "content-type": "application/json" },
        body: JSON.stringify({
          automation: opts.automation ?? true,
        }),
      });
    }
    if (
      (url.pathname === "/ledger/approve" ||
        url.pathname === "/ledger/reject") &&
      req.method() === "POST"
    ) {
      posted.push({ url: req.url(), body: req.postDataJSON() });
      return route.fulfill({
        status: 200,
        headers: { ...CORS, "content-type": "application/json" },
        body: JSON.stringify({ ok: true }),
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

  return {
    posted,
    goLive: () => {
      live = true;
    },
  };
}
