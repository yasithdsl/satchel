import { readSse } from "./sse.ts";

export const AGENT_URL =
  process.env.NEXT_PUBLIC_AGENT_URL ?? "http://127.0.0.1:8005";
export const XRAY_URL =
  process.env.NEXT_PUBLIC_XRAY_URL ?? "http://127.0.0.1:8006";

export interface XrayState {
  ts: string;
  main_funds: {
    fingerprint: string | null;
    addresses: number;
    utxos: number;
    balance_sats: number;
    available_sats: number;
  } | null;
  envelopes:
    | {
        index: number;
        budget_sats: number;
        assigned_to: string | null;
        status: string;
        balance_sats: number;
        available_sats: number | null;
      }[]
    | null;
  loss_sink: {
    wallet: string;
    confirmed_sats: number;
    pending_sats: number;
    last_address: string | null;
  } | null;
  random_nonce_signer: boolean | null;
  compromise_control: { enabled: boolean } | null;
  pending_approval: {
    pending: {
      kind: string;
      text: string;
      nonce: string;
      started_at: string;
    } | null;
  } | null;
  errors: Record<string, string>;
}

export async function* streamChat(
  message: string,
  sessionId: string | null,
  signal: AbortSignal,
): AsyncGenerator<Record<string, unknown>> {
  const response = await fetch(`${AGENT_URL}/chat`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ message, session_id: sessionId }),
    signal,
  });
  if (!response.ok) {
    throw new Error(`chat failed: ${response.status}`);
  }
  for await (const msg of readSse(response)) {
    yield JSON.parse(msg.data) as Record<string, unknown>;
  }
}

export async function getOrder(orderId: string): Promise<Record<string, unknown>> {
  const response = await fetch(`${AGENT_URL}/orders/${orderId}`);
  if (!response.ok) throw new Error(`order ${orderId}: ${response.status}`);
  return response.json() as Promise<Record<string, unknown>>;
}

export async function getState(): Promise<XrayState> {
  const response = await fetch(`${XRAY_URL}/state`);
  if (!response.ok) throw new Error(`xray state: ${response.status}`);
  return response.json() as Promise<XrayState>;
}

export async function setRandomNonce(enabled: boolean): Promise<void> {
  const response = await fetch(`${XRAY_URL}/demo/random-nonce`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ enabled }),
  });
  if (!response.ok) throw new Error(`random-nonce: ${response.status}`);
}

export async function mineBlock(): Promise<{ block_hash: string | null }> {
  const response = await fetch(`${XRAY_URL}/demo/mine`, { method: "POST" });
  if (!response.ok) throw new Error(`mine: ${response.status}`);
  return response.json() as Promise<{ block_hash: string | null }>;
}

export async function runCompromise(
  sessionId: string,
  requestSats?: number,
): Promise<Record<string, unknown>> {
  const response = await fetch(`${AGENT_URL}/demo/compromise`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(
      requestSats === undefined
        ? { session_id: sessionId }
        : { session_id: sessionId, request_sats: requestSats },
    ),
  });
  if (!response.ok) throw new Error(`compromise: ${response.status}`);
  return response.json() as Promise<Record<string, unknown>>;
}

export function ledgerScreenshotUrl(): string {
  return `${XRAY_URL}/ledger/screenshot`;
}

export async function getLedgerScreenText(): Promise<string[]> {
  const response = await fetch(`${XRAY_URL}/ledger/screen-text`);
  if (!response.ok) return [];
  const body = (await response.json()) as { texts?: string[] };
  return body.texts ?? [];
}

export interface FingerBody {
  action: "press" | "release" | "press-and-release";
  x: number;
  y: number;
  x2?: number;
  y2?: number;
  delay?: number;
}

export async function postFinger(body: FingerBody): Promise<void> {
  await fetch(`${XRAY_URL}/ledger/finger`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function getLedgerAutomation(): Promise<boolean> {
  try {
    const response = await fetch(`${XRAY_URL}/ledger/automation`);
    if (!response.ok) return false;
    const body = (await response.json()) as { automation?: boolean };
    return body.automation === true;
  } catch {
    return false;
  }
}

export type LedgerActionResult =
  | { ok: true }
  | {
      ok: false;
      /** nothing_pending: the request was already decided; automation_off: no demo buttons. */
      reason: "nothing_pending" | "automation_off" | "busy" | "error";
      detail: string;
    };

const LEDGER_REASONS = new Set(["nothing_pending", "automation_off", "busy"]);

export async function ledgerAction(
  action: "approve" | "reject",
): Promise<LedgerActionResult> {
  try {
    const response = await fetch(`${XRAY_URL}/ledger/${action}`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: "{}",
    });
    if (response.ok) return { ok: true };
    let body: { detail?: unknown; reason?: unknown } = {};
    try {
      body = (await response.json()) as typeof body;
    } catch {
      body = {};
    }
    const nested =
      body.detail && typeof body.detail === "object"
        ? (body.detail as { reason?: unknown; detail?: unknown })
        : null;
    const reason = String(nested?.reason ?? body.reason ?? "");
    const detail = String(nested?.detail ?? body.detail ?? "");
    return {
      ok: false,
      reason: LEDGER_REASONS.has(reason)
        ? (reason as "nothing_pending" | "automation_off" | "busy")
        : "error",
      detail: `${action} returned ${response.status}${detail ? `: ${detail}` : ""}`,
    };
  } catch (err) {
    return {
      ok: false,
      reason: "error",
      detail: `${action} failed: ${err instanceof Error ? err.message : String(err)}`,
    };
  }
}

/** DEMO ONLY: ask the x-ray to rerun the demo reset; it restarts every service. */
export async function resetDemo(): Promise<"started" | "disabled" | "busy" | "error"> {
  try {
    const response = await fetch(`${XRAY_URL}/demo/reset`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ confirm: true }),
    });
    if (response.ok) return "started";
    if (response.status === 404) return "disabled";
    if (response.status === 409) return "busy";
    console.warn("[satchel] reset:", response.status);
    return "error";
  } catch (err) {
    console.warn("[satchel] reset:", err);
    return "error";
  }
}

export async function xrayBootId(): Promise<string | null> {
  try {
    const response = await fetch(`${XRAY_URL}/health`, { cache: "no-store" });
    if (!response.ok) return null;
    const body = (await response.json()) as { boot_id?: string };
    return body.boot_id ?? null;
  } catch {
    return null;
  }
}
