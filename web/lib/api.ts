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
  await fetch(`${XRAY_URL}/demo/random-nonce`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ enabled }),
  });
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

export async function ledgerAction(
  action: "approve" | "reject",
): Promise<{ ok: boolean; status: number }> {
  try {
    const response = await fetch(`${XRAY_URL}/ledger/${action}`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: "{}",
    });
    return { ok: response.ok, status: response.status };
  } catch {
    return { ok: false, status: 0 };
  }
}
