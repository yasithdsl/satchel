import {
  createServer as httpCreateServer,
  type IncomingMessage,
  type Server,
  type ServerResponse,
} from "node:http";
import { emit } from "./events.ts";
import { toHttp } from "./payload.ts";
import { newNonce, renderText, validatePlan, type Plan } from "./plan.ts";
import { DeviceActionTimeout, isDeviceRejection } from "./dmk.ts";
import type { ApprovalDevice } from "./device.ts";
import type { SpeculosDriver } from "./speculos.ts";

export type ServerOptions = {
  device: ApprovalDevice;
  demo?: SpeculosDriver | null;
  demoAutomation?: boolean;
  timeoutMs?: number;
  now?: () => number;
  nonce?: () => string;
};

type Handler = (
  req: IncomingMessage,
  res: ServerResponse,
) => Promise<void> | void;

function sendJson(res: ServerResponse, status: number, body: unknown): void {
  const data = JSON.stringify(body);
  res.writeHead(status, { "content-type": "application/json" });
  res.end(data);
}

function sendBytes(
  res: ServerResponse,
  status: number,
  body: Uint8Array,
  contentType: string,
): void {
  res.writeHead(status, { "content-type": contentType });
  res.end(body);
}

async function readJson(req: IncomingMessage): Promise<unknown> {
  const chunks: Buffer[] = [];
  for await (const chunk of req) chunks.push(chunk as Buffer);
  try {
    return JSON.parse(Buffer.concat(chunks).toString("utf8"));
  } catch {
    throw new Error("malformed request");
  }
}

function formatSignature(r: string, s: string, v: number): string {
  const rr = (r.startsWith("0x") ? r.slice(2) : r).toLowerCase();
  const ss = (s.startsWith("0x") ? s.slice(2) : s).toLowerCase();
  if (!/^[0-9a-f]{64}$/.test(rr) || !/^[0-9a-f]{64}$/.test(ss)) {
    throw new Error("device returned a malformed signature");
  }
  const vv = v === 0 || v === 1 ? v + 27 : v;
  if (vv !== 27 && vv !== 28) {
    throw new Error(`device returned unexpected v=${v}`);
  }
  return `0x${rr}${ss}${vv.toString(16).padStart(2, "0")}`;
}

export function createServer(options: ServerOptions): Server {
  const {
    device,
    demo = null,
    demoAutomation = false,
    now = () => Math.floor(Date.now() / 1000),
    nonce = newNonce,
  } = options;
  let busy = false;
  let pending: {
    kind: string;
    text: string;
    nonce: string;
    started_at: string;
  } | null = null;

  if (demoAutomation && demo) {
    emit("approver", "demo_automation_enabled", "demo automation enabled");
  }

  const routes: Record<string, Record<string, Handler>> = {
    GET: {
      "/health": (_req, res) =>
        sendJson(res, 200, { ok: true, demo_automation: demoAutomation }),
      "/address": async (_req, res) => {
        try {
          sendJson(res, 200, await device.address());
        } catch (err) {
          sendJson(res, 502, {
            detail: `device error: ${(err as Error)?.message ?? err}`,
          });
        }
      },
      "/pending": (_req, res) => sendJson(res, 200, { pending }),
      ...(demoAutomation && demo
        ? {
            "/demo/screen": async (_req, res) => {
              emit("approver", "demo_action", "demo_action: screen");
              sendJson(res, 200, { events: await demo.screen() });
            },
            "/demo/screenshot": async (_req, res) => {
              emit("approver", "demo_action", "demo_action: screenshot");
              sendBytes(res, 200, await demo.screenshot(), "image/png");
            },
          }
        : {}),
    },
    POST: {
      "/approve": async (req, res) => {
        let body: unknown;
        try {
          body = await readJson(req);
        } catch (err) {
          sendJson(res, 422, { detail: (err as Error).message });
          return;
        }
        if (typeof body !== "object" || body === null || Array.isArray(body)) {
          sendJson(res, 422, { detail: "request body must be a JSON object" });
          return;
        }
        const req2 = body as { plan?: unknown; demo_auto?: unknown };
        let plan: Plan;
        try {
          plan = validatePlan(req2.plan);
          if (plan.kind === "envelope_grant" && plan.expires_at <= now()) {
            throw new Error("grant has already expired");
          }
        } catch (err) {
          sendJson(res, 422, { detail: (err as Error).message });
          return;
        }
        if (req2.demo_auto !== undefined) {
          if (req2.demo_auto !== "approve" && req2.demo_auto !== "reject") {
            sendJson(res, 422, {
              detail: "demo_auto must be 'approve' or 'reject'",
            });
            return;
          }
          if (!demoAutomation) {
            sendJson(res, 403, { detail: "demo automation is disabled" });
            return;
          }
        }
        if (busy) {
          sendJson(res, 409, { detail: "device busy" });
          return;
        }
        busy = true;
        const approvalNonce = nonce();
        const text = renderText(plan, approvalNonce);
        emit("approver", "approval_requested", `approval requested: ${text}`, {
          kind: plan.kind,
          text,
          nonce: approvalNonce,
        });
        pending = {
          kind: plan.kind,
          text,
          nonce: approvalNonce,
          started_at: new Date(now() * 1000).toISOString(),
        };
        try {
          const addressResult = await device.address();
          const signing = device.signPersonalMessage(text);
          const automation =
            req2.demo_auto === "approve"
              ? demo!.approveReview()
              : req2.demo_auto === "reject"
                ? demo!.rejectReview()
                : Promise.resolve();
          const [signResult, autoResult] = await Promise.allSettled([
            signing,
            automation,
          ]);
          if (signResult.status === "rejected") throw signResult.reason;
          if (autoResult.status === "rejected") {
            const reason =
              (autoResult.reason as Error)?.message ?? autoResult.reason;
            throw new Error(`demo automation failed: ${reason}`);
          }
          const signature = signResult.value;
          const signatureHex = formatSignature(
            signature.r,
            signature.s,
            signature.v,
          );
          emit("approver", "approval_granted", "approval granted", {
            nonce: approvalNonce,
            address: addressResult.address,
          });
          sendJson(
            res,
            200,
            toHttp("ledger_approval", {
              plan,
              text,
              nonce: approvalNonce,
              signature: signatureHex,
              address: addressResult.address,
              path: addressResult.path,
            }),
          );
        } catch (err) {
          if (isDeviceRejection(err)) {
            emit("approver", "approval_rejected", "approval rejected on device", {
              nonce: approvalNonce,
              reason: "Rejected on the Ledger",
            });
            sendJson(res, 409, {
              status: "rejected",
              reason: "Rejected on the Ledger",
              nonce: approvalNonce,
              text,
            });
          } else if (err instanceof DeviceActionTimeout) {
            emit("approver", "approval_failed", "approval timed out", {
              reason: "timeout",
            });
            sendJson(res, 504, { detail: "approval timed out" });
          } else {
            emit("approver", "approval_failed", "approval failed", {
              reason: (err as Error)?.message ?? String(err),
            });
            sendJson(res, 502, {
              detail: `device error: ${(err as Error)?.message ?? err}`,
            });
          }
        } finally {
          busy = false;
          pending = null;
        }
      },
      ...(demoAutomation && demo
        ? {
            "/demo/approve": async (_req, res) => {
              emit("approver", "demo_action", "demo_action: approve");
              try {
                await demo.approveReview();
                sendJson(res, 200, { ok: true });
              } catch (err) {
                sendJson(res, 502, {
                  detail: `demo error: ${(err as Error)?.message ?? err}`,
                });
              }
            },
            "/demo/reject": async (_req, res) => {
              emit("approver", "demo_action", "demo_action: reject");
              try {
                await demo.rejectReview();
                sendJson(res, 200, { ok: true });
              } catch (err) {
                sendJson(res, 502, {
                  detail: `demo error: ${(err as Error)?.message ?? err}`,
                });
              }
            },
          }
        : {}),
    },
  };

  const server = httpCreateServer((req, res) => {
    const method = req.method ?? "GET";
    const url = (req.url ?? "/").split("?")[0]!;
    const handler = routes[method]?.[url];
    if (!handler) {
      sendJson(res, 404, { detail: "not found" });
      return;
    }
    Promise.resolve(handler(req, res)).catch((err) => {
      try {
        sendJson(res, 500, { detail: String(err?.message ?? err) });
      } catch {}
    });
  });
  return server;
}
