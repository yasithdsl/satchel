import type { XrayState } from "./api.ts";
import type { XrayEvent } from "./xray.ts";
import { planAmountSats, planDeadline, planPurpose } from "./caption.ts";
import { usd } from "./money.ts";

export interface PendingApproval {
  kind: string;
  text: string;
  nonce: string | null;
}

/** A plain-English reading of the plan the Ledger is showing, without IDs. */
export function planSummary(pending: { kind: string; text: string }): {
  headline: string;
  detail: string | null;
} {
  const sats = planAmountSats(pending.text);
  const amount = sats !== null ? usd(sats) : null;
  if (pending.kind === "satchel_grant") {
    const deadline = planDeadline(pending.text);
    return {
      headline: amount
        ? `Create a ${amount} satchel for your agent, funded from main funds.`
        : "Create a satchel for your agent, funded from main funds.",
      detail: deadline
        ? `Its key goes to the agent, which can then spend it on its own. The approval is valid until ${deadline}.`
        : "Its key goes to the agent, which can then spend it on its own.",
    };
  }
  const purpose = planPurpose(pending.text);
  return {
    headline: amount
      ? `Pay ${amount} from your main funds.`
      : "Pay from your main funds.",
    detail: purpose ? `Labelled “${purpose}”.` : null,
  };
}

const APPROVER_OUTCOMES = new Set([
  "approval_requested",
  "approval_granted",
  "approval_rejected",
  "approval_failed",
]);

const STATE_GRACE_MS = 4_000;

/**
 * The approval on the device right now. It opens once the story has reached
 * the request (so the caption leads) and closes as soon as it is decided.
 * The polled state covers a reload in the middle of an approval and clears a
 * request whose outcome event never arrived.
 */
export function pendingApproval(
  events: XrayEvent[],
  playheadSeq: number,
  state: XrayState | null,
): PendingApproval | null {
  const fromState = state?.pending_approval?.pending ?? null;
  let last: XrayEvent | null = null;
  for (let i = events.length - 1; i >= 0; i--) {
    const e = events[i];
    if (e.component === "approver" && APPROVER_OUTCOMES.has(e.type)) {
      last = e;
      break;
    }
  }
  if (!last) {
    return fromState
      ? { kind: fromState.kind, text: fromState.text, nonce: fromState.nonce }
      : null;
  }
  if (last.type !== "approval_requested" || last.seq > playheadSeq) return null;
  const p = last.payload ?? {};
  const nonce = typeof p.nonce === "string" ? p.nonce : null;
  if (state?.pending_approval && fromState === null) {
    const stale = Date.parse(state.ts) - Date.parse(last.ts);
    if (Number.isFinite(stale) && stale > STATE_GRACE_MS) return null;
  }
  if (fromState && nonce && fromState.nonce !== nonce) {
    return { kind: fromState.kind, text: fromState.text, nonce: fromState.nonce };
  }
  return {
    kind: typeof p.kind === "string" ? p.kind : fromState?.kind ?? "",
    text: typeof p.text === "string" ? p.text : fromState?.text ?? "",
    nonce,
  };
}
