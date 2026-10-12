import { readSse, type SseMessage } from "./sse.ts";

export const AGENT_URL =
  process.env.NEXT_PUBLIC_AGENT_URL ?? "http://127.0.0.1:8005";
export const XRAY_URL =
  process.env.NEXT_PUBLIC_XRAY_URL ?? "http://127.0.0.1:8006";
export const SPECULOS_URL =
  process.env.NEXT_PUBLIC_SPECULOS_URL ?? "http://127.0.0.1:5001";

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

export async function* streamXrayEvents(
  signal: AbortSignal,
  backlog = 200,
): AsyncGenerator<SseMessage> {
  const response = await fetch(`${XRAY_URL}/events?backlog=${backlog}`, {
    signal,
  });
  if (!response.ok) {
    throw new Error(`xray events failed: ${response.status}`);
  }
  yield* readSse(response);
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
): Promise<Record<string, unknown>> {
  const response = await fetch(`${AGENT_URL}/demo/compromise`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ session_id: sessionId }),
  });
  if (!response.ok) throw new Error(`compromise: ${response.status}`);
  return response.json() as Promise<Record<string, unknown>>;
}
