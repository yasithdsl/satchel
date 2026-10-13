import type { XrayState } from "./api.ts";

const SOURCES = [
  "main_funds",
  "envelopes",
  "loss_sink",
  "random_nonce_signer",
  "compromise_control",
  "pending_approval",
] as const;

export function mergeState(
  prev: XrayState | null,
  next: XrayState,
): XrayState {
  if (!prev) return next;
  const merged = { ...next };
  const fields = merged as unknown as Record<string, unknown>;
  const keep = prev as unknown as Record<string, unknown>;
  for (const key of SOURCES) {
    if (next[key] == null && next.errors?.[key]) {
      fields[key] = keep[key];
    }
  }
  return merged;
}
