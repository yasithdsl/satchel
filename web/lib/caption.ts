import type { XrayEvent } from "./xray.ts";
import { btcTextToSats, usd, usdFromDollars } from "./money.ts";

/** Nodes in the x-ray device strip, in trust order. */
export type StripNode =
  | "agent"
  | "laptop"
  | "ledger"
  | "vault"
  | "signer"
  | "network"
  | "attacker";

export type Tone = "neutral" | "good" | "bad";

export type MomentKind = "purchase" | "compromise" | "blocked";

export interface Caption {
  text: string;
  tone: Tone;
  /** One node lights up, or two with a pulse from the first to the second. */
  nodes: StripNode[];
  simulation?: boolean;
  moment?: MomentKind;
}

/** What earlier events tell us, so later captions can say "$200" not "it". */
export interface StoryContext {
  compromiseActive: boolean;
  budgetByAgent: Record<string, number>;
  budgetByEnvelope: Record<number, number>;
  attackRequestSats: number | null;
  attackBudgetSats: number | null;
}

export function newContext(): StoryContext {
  return {
    compromiseActive: false,
    budgetByAgent: {},
    budgetByEnvelope: {},
    attackRequestSats: null,
    attackBudgetSats: null,
  };
}

/**
 * Events the audience never needs: setup, polling exports, bookkeeping, and
 * hops whose story is told by a neighbouring event (noted alongside).
 */
export const SILENT_EVENT_TYPES = new Set<string>([
  // setup and polling
  "seed_created",
  "vault_unlocked",
  "unlock_failed",
  "vault_reset",
  "envelopes_allocated",
  "envelopes_exported",
  "addresses_exported",
  "envelope_funded",
  "main_fund_funded",
  "main_funds_funded",
  "receive_addresses_exported",
  "setup_completed",
  "setup_failed",
  "demo_automation_enabled",
  "demo_action",
  "search",
  // flow bookkeeping; the outcome event carries the story
  "grant_completed",
  "grant_failed",
  "spend_completed",
  "spend_failed",
  "release_requested",
  "envelopes_fetched",
  "plan_sent_to_approver", // approver approval_requested
  "approval_received", // approver approval_granted
  "key_release_received", // vault envelope_released
  "keys_released", // vault spend_keys_released
  "change_address_exported",
  "utxos_selected",
  "signed_tx_received", // signer psbt_signed
  "verification_received", // vault verification_passed / _failed
  "random_nonce_signing", // signer psbt_signed
  "order_created", // agent buy_product
  "tool_result",
  "compromise_finished", // the rejection caption stays on screen
]);

/** Laptop hops that share a name with the event that tells their story. */
const SILENT_LAPTOP_HOPS = new Set<string>([
  "approval_rejected", // approver approval_rejected
]);

/** Tool calls that are bookkeeping, or announced by a richer event. */
const SILENT_TOOLS = new Set<string>([
  "check_budget",
  "check_order",
  "request_large_purchase", // agent large_purchase_notice
]);

export function isSilent(event: XrayEvent): boolean {
  if (SILENT_EVENT_TYPES.has(event.type)) return true;
  if (event.component === "laptop" && SILENT_LAPTOP_HOPS.has(event.type)) {
    return true;
  }
  return (
    event.type === "tool_call" &&
    SILENT_TOOLS.has(String(event.payload?.tool ?? ""))
  );
}

function num(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function str(value: unknown): string | null {
  return typeof value === "string" && value ? value : null;
}

function cap(
  text: string,
  nodes: StripNode[],
  tone: Tone = "neutral",
  extra: Partial<Caption> = {},
): Caption {
  return { text, nodes, tone, ...extra };
}

/** Amount on a Ledger plan, read from its text ("(0.002 BTC)" or "Pay 0.05 BTC"). */
export function planAmountSats(text: string | null): number | null {
  if (!text) return null;
  const match =
    /\(([\d.]+) BTC\)/.exec(text) ?? /^Pay ([\d.]+) BTC/.exec(text);
  return match ? btcTextToSats(match[1]) : null;
}

/** Fold an event into the context. Call before captionFor for the same event. */
export function observe(ctx: StoryContext, event: XrayEvent): StoryContext {
  const p = event.payload ?? {};
  switch (event.type) {
    case "wallet_loaded": {
      const budget = num(p.budget_sats);
      const index = num(p.envelope_index);
      const agent = str(p.agent_id);
      if (budget === null) return ctx;
      return {
        ...ctx,
        budgetByAgent: agent ? { ...ctx.budgetByAgent, [agent]: budget } : ctx.budgetByAgent,
        budgetByEnvelope:
          index !== null ? { ...ctx.budgetByEnvelope, [index]: budget } : ctx.budgetByEnvelope,
      };
    }
    case "compromise_started": {
      const agent = str(p.agent_id);
      return {
        ...ctx,
        compromiseActive: true,
        attackRequestSats: null,
        attackBudgetSats: agent ? (ctx.budgetByAgent[agent] ?? null) : null,
      };
    }
    case "compromise_large_spend_requested":
      return { ...ctx, attackRequestSats: num(p.amount_sats) };
    case "compromise_finished":
      return { ...ctx, compromiseActive: false };
    default:
      return ctx;
  }
}

function searchText(input: Record<string, unknown>): string {
  const query = str(input.query);
  const max = num(input.max_price_usd);
  if (!query) return "Your agent is searching the shop.";
  return max !== null
    ? `Your agent is searching the shop for ${query} under ${usdFromDollars(max)}.`
    : `Your agent is searching the shop for ${query}.`;
}

function agentToolCall(event: XrayEvent): Caption | null {
  const p = event.payload ?? {};
  const input = (p.input ?? {}) as Record<string, unknown>;
  switch (p.tool) {
    case "search_products":
      return cap(searchText(input), ["agent"]);
    case "get_product_details":
      return cap("Your agent is reading a product page.", ["agent"]);
    case "suggest_products": {
      const n = Array.isArray(input.product_ids) ? input.product_ids.length : 0;
      return cap(
        n > 0
          ? `Your agent picked ${n} option${n === 1 ? "" : "s"} to show you.`
          : "Your agent picked some options to show you.",
        ["agent"],
      );
    }
    case "request_budget": {
      const amount = num(input.amount_usd);
      return cap(
        amount !== null
          ? `Your agent is asking for a ${usdFromDollars(amount)} budget.`
          : "Your agent is asking for a budget.",
        ["agent", "laptop"],
      );
    }
    case "buy_product":
      return cap("Your agent is placing the order.", ["agent"]);
    default:
      return null;
  }
}

function agentEvent(event: XrayEvent, ctx: StoryContext): Caption | null {
  const p = event.payload ?? {};
  const sim = { simulation: true };
  switch (event.type) {
    case "tool_call":
      return agentToolCall(event);
    case "wallet_loaded": {
      const budget = num(p.budget_sats);
      return cap(
        budget !== null
          ? `Your agent can now spend up to ${usd(budget)} on its own.`
          : "Your agent now has a prepaid budget.",
        ["agent"],
        "good",
      );
    }
    case "payment_sent": {
      if (ctx.compromiseActive) return null;
      const amount = num(p.amount_sats);
      const index = num(p.envelope_index);
      const budget = index !== null ? ctx.budgetByEnvelope[index] : undefined;
      const paid = amount !== null ? `paid ${usd(amount)}` : "paid";
      const from = budget !== undefined ? `its ${usd(budget)} budget` : "its budget";
      return cap(
        `Your agent ${paid} from ${from}. No Ledger tap needed.`,
        ["agent", "network"],
        "good",
        { moment: "purchase" },
      );
    }
    case "payment_rejected":
      return cap("Your agent's wallet refused that payment.", ["agent"]);
    case "payment_failed":
      return cap("The payment didn't reach the network.", ["agent", "network"]);
    case "large_purchase_notice":
      return cap(
        "Too big for the budget, so your agent asks to pay from main funds.",
        ["agent", "laptop"],
      );
    case "compromise_started":
      return cap(
        "Simulation: an attacker now fully controls your agent.",
        ["agent"],
        "bad",
        sim,
      );
    case "compromise_envelope_drained": {
      const amount = num(p.amount_sats);
      return cap(
        amount !== null
          ? `The attacker sent the agent's budget to their own wallet: ${usd(amount)}.`
          : "The attacker sent the agent's budget to their own wallet.",
        ["agent", "attacker"],
        "bad",
        { ...sim, moment: "compromise" },
      );
    }
    case "compromise_envelope_empty":
      return cap(
        "The attacker found nothing left in the agent's budget.",
        ["agent"],
        "bad",
        sim,
      );
    case "compromise_large_spend_requested": {
      const amount = num(p.amount_sats);
      return cap(
        amount !== null
          ? `The attacker asks for ${usd(amount)} more from your main funds.`
          : "The attacker asks for more from your main funds.",
        ["agent", "laptop"],
        "bad",
        sim,
      );
    }
    case "compromise_large_spend_blocked": {
      const amount =
        ctx.attackRequestSats !== null ? `${usd(ctx.attackRequestSats)} ` : "";
      return p.stage === "approval"
        ? cap(
            `Request for ${amount}more: rejected on your Ledger.`,
            ["ledger"],
            "good",
            sim,
          )
        : cap(
            `Request for ${amount}more: blocked. Nothing was sent.`,
            ["vault"],
            "good",
            sim,
          );
    }
    case "compromise_large_spend_approved": {
      const amount =
        ctx.attackRequestSats !== null ? usd(ctx.attackRequestSats) : "Money";
      return cap(
        `You approved the attacker's request. ${amount} left your main funds.`,
        ["ledger", "attacker"],
        "bad",
        sim,
      );
    }
    default:
      return null;
  }
}

function approverEvent(event: XrayEvent, ctx: StoryContext): Caption | null {
  const p = event.payload ?? {};
  switch (event.type) {
    case "approval_requested": {
      const sats = planAmountSats(str(p.text));
      if (p.kind === "envelope_grant") {
        return cap(
          sats !== null
            ? `Your laptop is asking the Ledger to approve a ${usd(sats)} budget.`
            : "Your laptop is asking the Ledger to approve a budget.",
          ["laptop", "ledger"],
        );
      }
      return cap(
        sats !== null
          ? `Your laptop is asking the Ledger to approve paying ${usd(sats)} from main funds.`
          : "Your laptop is asking the Ledger to approve a payment from main funds.",
        ["laptop", "ledger"],
        ctx.compromiseActive ? "bad" : "neutral",
        ctx.compromiseActive ? { simulation: true } : {},
      );
    }
    case "approval_granted":
      return cap(
        "Approved on your Ledger. The device signed the plan.",
        ["ledger"],
        "good",
      );
    case "approval_rejected":
      if (ctx.compromiseActive) return null;
      return cap("Rejected on your Ledger. Nothing was signed.", ["ledger"]);
    case "approval_failed":
      return cap(
        "The Ledger didn't answer in time, so nothing was approved.",
        ["ledger"],
      );
    default:
      return null;
  }
}

function laptopEvent(event: XrayEvent): Caption | null {
  switch (event.type) {
    case "approval_sent_to_vault":
      return cap(
        "Your laptop carried the signed approval to the offline vault.",
        ["laptop", "vault"],
      );
    case "key_delivered_to_agent":
      return cap(
        "Your laptop handed that one budget key to your agent.",
        ["laptop", "agent"],
      );
    case "psbt_built":
      return cap(
        "Your laptop drafted the payment from main funds. It has no keys to sign it.",
        ["laptop"],
      );
    case "keys_sent_to_signer":
      return cap(
        "Your laptop passed the draft and those keys to the offline signer.",
        ["laptop", "signer"],
      );
    case "broadcast":
      return cap(
        "Your laptop sent the verified payment to the Bitcoin network.",
        ["laptop", "network"],
        "good",
      );
    default:
      return null;
  }
}

function vaultEvent(event: XrayEvent): Caption | null {
  switch (event.type) {
    case "envelope_released":
      return cap(
        "The vault checked your Ledger signature and released one budget key.",
        ["vault", "laptop"],
        "good",
      );
    case "spend_keys_released":
      return cap(
        "The vault checked your Ledger signature and released keys for this payment only.",
        ["vault", "laptop"],
        "good",
      );
    case "release_refused":
      return cap("The vault refused to release any keys.", ["vault"], "bad");
    case "verification_passed":
      return cap(
        "The vault checked the signer's signature: it matches.",
        ["signer", "vault"],
        "good",
      );
    case "verification_failed":
      return cap(
        "Vault blocked the transaction: the signer's signature didn't match. Nothing was sent.",
        ["signer", "vault"],
        "bad",
        { moment: "blocked" },
      );
    default:
      return null;
  }
}

function signerEvent(event: XrayEvent): Caption | null {
  const p = event.payload ?? {};
  switch (event.type) {
    case "psbt_signed":
      return p.nonce === "random"
        ? cap(
            "The signer signed the payment, but not the honest way.",
            ["signer", "laptop"],
            "bad",
          )
        : cap(
            "The signer signed the payment with the keys it was given.",
            ["signer", "laptop"],
          );
    case "random_nonce_enabled":
      return cap(
        "Demo: the signer now cheats when it signs.",
        ["signer"],
        "bad",
        { simulation: true },
      );
    case "random_nonce_disabled":
      return cap("Demo: the signer is honest again.", ["signer"]);
    case "sign_refused":
      return cap("The signer refused to sign.", ["signer"]);
    default:
      return null;
  }
}

function marketplaceEvent(event: XrayEvent): Caption | null {
  switch (event.type) {
    case "payment_seen":
      return cap(
        "The shop sees the payment. It confirms with the next block.",
        ["network"],
      );
    case "order_paid":
      return cap(
        "The payment confirmed. Your order is paid.",
        ["network"],
        "good",
      );
    default:
      return null;
  }
}

/** The one plain-English sentence for an event, or null if it stays silent. */
export function captionFor(
  event: XrayEvent,
  ctx: StoryContext,
): Caption | null {
  if (isSilent(event)) return null;
  switch (event.component) {
    case "agent":
      return agentEvent(event, ctx);
    case "approver":
      return approverEvent(event, ctx);
    case "laptop":
      return laptopEvent(event);
    case "vault":
      return vaultEvent(event);
    case "signer":
      return signerEvent(event);
    case "marketplace":
      return marketplaceEvent(event);
    case "network":
      return event.type === "block_mined"
        ? cap("A new Bitcoin block was mined.", ["network"])
        : null;
    default:
      return null;
  }
}

export interface Captioned {
  event: XrayEvent;
  caption: Caption;
  ctx: StoryContext;
}

/** Caption a run of events in order, threading the context through. */
export function captionAll(
  events: XrayEvent[],
  start: StoryContext = newContext(),
): { items: Captioned[]; ctx: StoryContext } {
  let ctx = start;
  const items: Captioned[] = [];
  for (const event of events) {
    ctx = observe(ctx, event);
    const caption = captionFor(event, ctx);
    if (caption) items.push({ event, caption, ctx });
  }
  return { items, ctx };
}
