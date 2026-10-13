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

/** The story arc a step belongs to; drives the kicker and the stage visual. */
export type Chapter = "satchel" | "shopping" | "payment" | "attack" | "signer";

/** What the x-ray stage shows next to the device strip for a step. */
export type Visual = "satchel" | "store" | "attack" | "signer";

export interface Caption {
  /** One plain-English sentence: what just happened. */
  text: string;
  /** Why it matters for safety; one or two short sentences. */
  why?: string;
  tone: Tone;
  /** One node lights up, or two with a pulse from the first to the second. */
  nodes: StripNode[];
  chapter?: Chapter;
  visual?: Visual;
  /** Position in a chapter with a known shape, such as satchel creation. */
  step?: { index: number; total: number };
  simulation?: boolean;
  moment?: MomentKind;
}

export interface StoreItem {
  id: string;
  name: string;
  category: string | null;
  priceSats: number | null;
  deliveryDate: string | null;
}

export type SatchelMilestone =
  | "asked"
  | "key"
  | "drafted"
  | "approved"
  | "keys"
  | "signed"
  | "verified"
  | "confirmed"
  | "handed";

/** What earlier events tell us, so later captions and panels can be specific. */
export interface StoryContext {
  compromiseActive: boolean;
  signerCheating: boolean;
  /** Which laptop flow the latest hops belong to. */
  flow: "grant" | "spend" | null;
  budgetByAgent: Record<string, number>;
  budgetByEnvelope: Record<number, number>;
  /** The satchel being created, or the last one created. */
  satchel: {
    budgetSats: number | null;
    path: string | null;
    milestones: SatchelMilestone[];
  };
  store: {
    query: string | null;
    maxUsd: number | null;
    results: StoreItem[];
    suggested: string[];
    chosen: string | null;
    paidSats: number | null;
    changeSats: number | null;
    confirmed: boolean;
  };
  spend: { amountSats: number | null; purpose: string | null };
  attack: {
    budgetSats: number | null;
    drainedSats: number | null;
    requestSats: number | null;
    outcome: "pending" | "rejected" | "approved" | null;
  };
  signer: { verdict: "pending" | "honest" | "forged" | null };
}

export function newContext(): StoryContext {
  return {
    compromiseActive: false,
    signerCheating: false,
    flow: null,
    budgetByAgent: {},
    budgetByEnvelope: {},
    satchel: { budgetSats: null, path: null, milestones: [] },
    store: {
      query: null,
      maxUsd: null,
      results: [],
      suggested: [],
      chosen: null,
      paidSats: null,
      changeSats: null,
      confirmed: false,
    },
    spend: { amountSats: null, purpose: null },
    attack: { budgetSats: null, drainedSats: null, requestSats: null, outcome: null },
    signer: { verdict: null },
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
  "search", // marketplace: the agent's search_products call tells it
  // flow bookkeeping; the outcome event carries the story
  "grant_completed",
  "grant_failed",
  "spend_completed",
  "spend_failed",
  "release_requested",
  "envelopes_fetched",
  "plan_sent_to_approver", // approver approval_requested
  "approval_received", // approver approval_granted
  "approval_sent_to_vault", // vault *_released
  "key_release_received", // vault satchel_released
  "key_delivered_to_agent", // agent wallet_loaded
  "keys_released", // vault *_released
  "keys_sent_to_signer", // signer psbt_signed
  "change_address_exported",
  "utxos_selected",
  "signed_tx_received", // signer psbt_signed
  "verification_received", // vault verification_passed / _failed
  "funding_proof_sent", // vault satchel_released
  "random_nonce_signing", // signer psbt_signed
  "order_created", // agent buy_product
  "payment_seen", // marketplace order_paid
  "tool_result",
  "compromise_finished", // the rejection caption stays on screen
]);

/** Laptop hops that share a name with the event that tells their story. */
const SILENT_LAPTOP_HOPS = new Set<string>([
  "approval_rejected", // approver approval_rejected
  "satchel_reserved", // vault satchel_reserved
]);

/** Tool calls that are bookkeeping, or announced by a richer event. */
const SILENT_TOOLS = new Set<string>([
  "check_budget",
  "check_order",
  "get_product_details",
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

/** Satchel creation always runs these steps, in this order. */
export const SATCHEL_STEPS = [
  "tool_call:request_budget",
  "satchel_reserved",
  "psbt_built",
  "approval_requested",
  "approval_granted",
  "satchel_funding_released",
  "psbt_signed",
  "verification_passed",
  "funding_confirmed",
  "satchel_released",
  "wallet_loaded",
] as const;

function num(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function str(value: unknown): string | null {
  return typeof value === "string" && value ? value : null;
}

function humanise(id: string): string {
  return id
    .split("-")
    .filter(Boolean)
    .map((w) => w[0].toUpperCase() + w.slice(1))
    .join(" ");
}

/** "$799 " for a known amount, "" otherwise, to slot in front of a noun. */
function amountOf(sats: number | null): string {
  return sats !== null ? `${usd(sats)} ` : "";
}

/** Amount on a Ledger plan, read from its text ("0.002 BTC satchel" or "Pay 0.05 BTC"). */
export function planAmountSats(text: string | null): number | null {
  if (!text) return null;
  const match =
    /^Create a ([\d.]+) BTC satchel/.exec(text) ??
    /\(([\d.]+) BTC\)/.exec(text) ??
    /^Pay ([\d.]+) BTC/.exec(text);
  return match ? btcTextToSats(match[1]) : null;
}

function addMilestone(
  ctx: StoryContext,
  milestone: SatchelMilestone,
): StoryContext {
  if (ctx.satchel.milestones.includes(milestone)) return ctx;
  return {
    ...ctx,
    satchel: { ...ctx.satchel, milestones: [...ctx.satchel.milestones, milestone] },
  };
}

function storeItems(raw: unknown): StoreItem[] {
  if (!Array.isArray(raw)) return [];
  return raw.flatMap((r) => {
    const p = (r ?? {}) as Record<string, unknown>;
    const id = str(p.id);
    const name = str(p.name);
    if (!id || !name) return [];
    return [
      {
        id,
        name,
        category: str(p.category),
        priceSats: num(p.price_sats),
        deliveryDate: str(p.delivery_date),
      },
    ];
  });
}

/** Fold an event into the context. Call before captionFor for the same event. */
export function observe(ctx: StoryContext, event: XrayEvent): StoryContext {
  const p = event.payload ?? {};
  const input = (p.input ?? {}) as Record<string, unknown>;
  if (event.component === "laptop" && (p.flow === "grant" || p.flow === "spend")) {
    ctx = { ...ctx, flow: p.flow };
  }
  switch (event.type) {
    case "tool_call":
      if (p.tool === "request_budget") {
        const amount = num(input.amount_usd);
        return {
          ...ctx,
          flow: "grant",
          satchel: {
            budgetSats: amount !== null ? Math.round(amount * 1000) : null,
            path: null,
            milestones: ["asked"],
          },
        };
      }
      if (p.tool === "search_products") {
        return {
          ...ctx,
          store: {
            ...newContext().store,
            query: str(input.query),
            maxUsd: num(input.max_price_usd),
          },
        };
      }
      if (p.tool === "suggest_products") {
        const ids = Array.isArray(input.product_ids)
          ? input.product_ids.filter((x): x is string => typeof x === "string")
          : [];
        return { ...ctx, store: { ...ctx.store, suggested: ids } };
      }
      if (p.tool === "buy_product") {
        const id = str(input.product_id);
        const known = ctx.store.results.some((r) => r.id === id);
        const results =
          id && !known
            ? [
                ...ctx.store.results,
                { id, name: humanise(id), category: null, priceSats: null, deliveryDate: null },
              ]
            : ctx.store.results;
        return {
          ...ctx,
          store: { ...ctx.store, results, chosen: id, paidSats: null, confirmed: false },
        };
      }
      return ctx;
    case "search":
      if (event.component !== "marketplace") return ctx;
      return { ...ctx, store: { ...ctx.store, results: storeItems(p.results) } };
    case "order_created": {
      const amount = num(p.amount_sats);
      const id = str(p.product_id);
      return {
        ...ctx,
        spend: { ...ctx.spend, amountSats: amount },
        store: {
          ...ctx.store,
          results: ctx.store.results.map((r) =>
            r.id === id && r.priceSats === null ? { ...r, priceSats: amount } : r,
          ),
        },
      };
    }
    case "satchel_reserved":
      if (event.component !== "vault") return ctx;
      return addMilestone(
        {
          ...ctx,
          satchel: {
            ...ctx.satchel,
            budgetSats: num(p.budget_sats) ?? ctx.satchel.budgetSats,
            path: str(p.path),
          },
        },
        "key",
      );
    case "psbt_built":
      return ctx.flow === "grant" ? addMilestone(ctx, "drafted") : ctx;
    case "approval_requested": {
      const text = str(p.text);
      if (p.kind === "large_spend") {
        const purpose = /for (.+?), PSBT/.exec(text ?? "");
        return {
          ...ctx,
          flow: "spend",
          spend: {
            amountSats: planAmountSats(text) ?? ctx.spend.amountSats,
            purpose: purpose?.[1] ?? null,
          },
          attack: ctx.compromiseActive ? { ...ctx.attack, outcome: "pending" } : ctx.attack,
        };
      }
      return { ...ctx, flow: "grant" };
    }
    case "approval_granted":
      return ctx.flow === "grant" ? addMilestone(ctx, "approved") : ctx;
    case "satchel_funding_released":
      return addMilestone(ctx, "keys");
    case "psbt_signed":
      return ctx.flow === "grant"
        ? addMilestone(ctx, "signed")
        : { ...ctx, signer: { verdict: "pending" } };
    case "verification_passed":
      return ctx.flow === "grant"
        ? addMilestone(ctx, "verified")
        : { ...ctx, signer: { verdict: "honest" } };
    case "verification_failed":
      return { ...ctx, signer: { verdict: "forged" } };
    case "funding_confirmed":
      return addMilestone(ctx, "confirmed");
    case "satchel_released":
      return addMilestone(ctx, "handed");
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
    case "payment_sent":
      if (ctx.compromiseActive) return ctx;
      return {
        ...ctx,
        store: { ...ctx.store, paidSats: num(p.amount_sats), changeSats: num(p.change_sats) },
      };
    case "order_paid":
      return { ...ctx, store: { ...ctx.store, confirmed: true } };
    case "random_nonce_enabled":
      return { ...ctx, signerCheating: true, signer: { verdict: null } };
    case "random_nonce_disabled":
      return { ...ctx, signerCheating: false };
    case "compromise_started": {
      const agent = str(p.agent_id);
      return {
        ...ctx,
        compromiseActive: true,
        attack: {
          budgetSats: agent ? (ctx.budgetByAgent[agent] ?? null) : null,
          drainedSats: null,
          requestSats: null,
          outcome: null,
        },
      };
    }
    case "compromise_envelope_drained":
      return { ...ctx, attack: { ...ctx.attack, drainedSats: num(p.amount_sats) } };
    case "compromise_large_spend_requested":
      return {
        ...ctx,
        spend: { amountSats: num(p.amount_sats), purpose: str(p.purpose) },
        attack: { ...ctx.attack, requestSats: num(p.amount_sats) },
      };
    case "compromise_large_spend_blocked":
      return { ...ctx, attack: { ...ctx.attack, outcome: "rejected" } };
    case "compromise_large_spend_approved":
      return { ...ctx, attack: { ...ctx.attack, outcome: "approved" } };
    case "compromise_finished":
      return { ...ctx, compromiseActive: false };
    default:
      return ctx;
  }
}

function cap(
  text: string,
  nodes: StripNode[],
  tone: Tone = "neutral",
  extra: Partial<Caption> = {},
): Caption {
  return { text, nodes, tone, ...extra };
}

function satchelStep(key: (typeof SATCHEL_STEPS)[number]): Partial<Caption> {
  return {
    chapter: "satchel",
    visual: "satchel",
    step: { index: SATCHEL_STEPS.indexOf(key) + 1, total: SATCHEL_STEPS.length },
  };
}

const ATTACK = { simulation: true, chapter: "attack", visual: "attack" } as const;

function searchText(input: Record<string, unknown>): string {
  const query = str(input.query);
  const max = num(input.max_price_usd);
  if (!query) return "Your agent browses the store.";
  return max !== null
    ? `Your agent browses the store for ${query} under ${usdFromDollars(max)}.`
    : `Your agent browses the store for ${query}.`;
}

function agentToolCall(event: XrayEvent, ctx: StoryContext): Caption | null {
  const p = event.payload ?? {};
  const input = (p.input ?? {}) as Record<string, unknown>;
  switch (p.tool) {
    case "request_budget": {
      const amount = num(input.amount_usd);
      return cap(
        amount !== null
          ? `Your agent asks for a ${usdFromDollars(amount)} budget.`
          : "Your agent asks for a budget.",
        ["agent", "laptop"],
        "neutral",
        {
          ...satchelStep("tool_call:request_budget"),
          why: "It holds no keys to your money, so all it can do is ask. The system takes it from here.",
        },
      );
    }
    case "search_products":
      return cap(searchText(input), ["agent"], "neutral", {
        chapter: "shopping",
        visual: "store",
        why: "It shops by itself, inside the satchel you approved.",
      });
    case "suggest_products": {
      const n = Array.isArray(input.product_ids) ? input.product_ids.length : 0;
      return cap(
        n > 0
          ? `It shortlists the ${n} best match${n === 1 ? "" : "es"} for you.`
          : "It shortlists the best matches for you.",
        ["agent"],
        "neutral",
        { chapter: "shopping", visual: "store", why: "You see them as cards in the chat." },
      );
    }
    case "buy_product": {
      const item = ctx.store.results.find((r) => r.id === ctx.store.chosen);
      const price = item?.priceSats ?? null;
      const budget = ctx.satchel.budgetSats;
      const name = item?.name ?? "the item";
      return cap(
        price !== null ? `It checks out: ${name}, ${usd(price)}.` : `It checks out: ${name}.`,
        ["agent"],
        "neutral",
        {
          chapter: "shopping",
          visual: "store",
          why:
            price !== null && budget !== null
              ? price <= budget
                ? `${usd(price)} fits in its ${usd(budget)} satchel, so it can pay on its own.`
                : `That's more than its ${usd(budget)} satchel.`
              : undefined,
        },
      );
    }
    default:
      return null;
  }
}

function agentEvent(event: XrayEvent, ctx: StoryContext): Caption | null {
  const p = event.payload ?? {};
  switch (event.type) {
    case "tool_call":
      return agentToolCall(event, ctx);
    case "wallet_loaded": {
      const budget = num(p.budget_sats);
      return cap(
        `Your agent now holds a ${amountOf(budget)}satchel.`,
        ["laptop", "agent"],
        "good",
        {
          ...satchelStep("wallet_loaded"),
          why:
            budget !== null
              ? `It can shop on its own, with no more Ledger taps, as long as it stays within ${usd(budget)}.`
              : "It can shop on its own, within the satchel.",
        },
      );
    }
    case "payment_sent": {
      if (ctx.compromiseActive) return null;
      const amount = num(p.amount_sats);
      const change = num(p.change_sats);
      return cap(
        `Paid ${amount !== null ? usd(amount) : "the order"} from the satchel. No Ledger tap needed.`,
        ["agent", "network"],
        "good",
        {
          chapter: "shopping",
          visual: "store",
          moment: "purchase",
          why:
            change !== null
              ? `${usd(change)} is left in the satchel. Your main funds were never touched.`
              : "Your main funds were never touched.",
        },
      );
    }
    case "payment_rejected":
      return cap("Your agent's wallet refused that payment.", ["agent"]);
    case "payment_failed":
      return cap("The payment didn't reach the network.", ["agent", "network"]);
    case "large_purchase_notice":
      return cap(
        "Too big for the satchel, so your agent asks to pay from main funds.",
        ["agent", "laptop"],
        "neutral",
        {
          chapter: "payment",
          visual: ctx.signerCheating ? "signer" : undefined,
          why: "Anything over the limit needs a fresh approval on your Ledger.",
        },
      );
    case "compromise_started":
      return cap("Simulated attack: your agent is fully compromised.", ["agent"], "bad", {
        ...ATTACK,
        why: "Assume the worst: malware or a prompt injection gives an attacker full control of the agent and its satchel key. What can they take?",
      });
    case "compromise_envelope_drained":
      return cap(
        `The attacker sends the satchel's ${amountOf(num(p.amount_sats))}to their own wallet.`,
        ["agent", "attacker"],
        "bad",
        {
          ...ATTACK,
          moment: "compromise",
          why: "That's all they can take. The satchel key unlocks this one satchel and nothing else.",
        },
      );
    case "compromise_envelope_empty":
      return cap("The attacker finds the satchel already empty.", ["agent"], "bad", ATTACK);
    case "compromise_large_spend_requested": {
      const amount = num(p.amount_sats);
      return cap(
        `Then they ask for ${amount !== null ? usd(amount) : "more"} from your main funds.`,
        ["agent", "laptop"],
        "bad",
        {
          ...ATTACK,
          why: "The agent can ask, like any request. But main funds only move with your Ledger's signature.",
        },
      );
    }
    case "compromise_large_spend_blocked": {
      const lost = ctx.attack.drainedSats ?? ctx.attack.budgetSats;
      return p.stage === "approval"
        ? cap(
            `Request for ${amountOf(ctx.attack.requestSats)}more: rejected on your Ledger.`,
            ["ledger"],
            "good",
            { ...ATTACK, why: `Lost: the ${amountOf(lost)}satchel. Main funds: untouched.` },
          )
        : cap(
            `Request for ${amountOf(ctx.attack.requestSats)}more: blocked. Nothing was sent.`,
            ["vault"],
            "good",
            ATTACK,
          );
    }
    case "compromise_large_spend_approved":
      return cap(
        `You approved the attacker's request. ${ctx.attack.requestSats !== null ? usd(ctx.attack.requestSats) : "Money"} left your main funds.`,
        ["ledger", "attacker"],
        "bad",
        ATTACK,
      );
    default:
      return null;
  }
}

function approverEvent(event: XrayEvent, ctx: StoryContext): Caption | null {
  const p = event.payload ?? {};
  switch (event.type) {
    case "approval_requested": {
      const sats = planAmountSats(str(p.text));
      if (p.kind === "satchel_grant") {
        return cap(
          `Your laptop asks the Ledger to approve a ${amountOf(sats)}satchel.`,
          ["laptop", "ledger"],
          "neutral",
          {
            ...satchelStep("approval_requested"),
            why: "One tap covers it all: fund the satchel from main funds and hand its key to the agent. The rest is automatic.",
          },
        );
      }
      if (ctx.compromiseActive) {
        return cap(
          `Your Ledger shows the attacker's request: ${amountOf(sats)}from main funds.`,
          ["laptop", "ledger"],
          "bad",
          {
            ...ATTACK,
            why: `Labelled “${ctx.spend.purpose ?? "agent top-up"}”. You didn't ask for this, so you reject it.`,
          },
        );
      }
      return cap(
        `Your laptop asks the Ledger to approve paying ${amountOf(sats)}from main funds.`,
        ["laptop", "ledger"],
        "neutral",
        {
          chapter: "payment",
          visual: ctx.signerCheating ? "signer" : undefined,
          why: "Read the amount and what it's for on the device before you approve.",
        },
      );
    }
    case "approval_granted":
      if (ctx.flow === "grant") {
        return cap("Approved on your Ledger.", ["ledger"], "good", {
          ...satchelStep("approval_granted"),
          why: "The Ledger signed the exact plan text. The vault will refuse anything that doesn't match it.",
        });
      }
      return cap("Approved on your Ledger.", ["ledger"], ctx.compromiseActive ? "bad" : "good", {
        chapter: ctx.compromiseActive ? "attack" : "payment",
        visual: ctx.signerCheating ? "signer" : undefined,
        why: "The Ledger signed the exact plan. Now the vault takes over.",
      });
    case "approval_rejected":
      if (ctx.compromiseActive) return null;
      return cap("Rejected on your Ledger. Nothing was signed.", ["ledger"]);
    case "approval_failed":
      return cap("The Ledger didn't answer in time, so nothing was approved.", ["ledger"]);
    default:
      return null;
  }
}

function laptopEvent(event: XrayEvent, ctx: StoryContext): Caption | null {
  switch (event.type) {
    case "psbt_built":
      if (ctx.flow === "grant") {
        return cap(
          `Your laptop drafts the funding: ${amountOf(ctx.satchel.budgetSats)}from main funds into the satchel.`,
          ["laptop"],
          "neutral",
          {
            ...satchelStep("psbt_built"),
            why: "The laptop is online, so it stores no keys. It can only propose.",
          },
        );
      }
      return cap(
        `Your laptop drafts the ${amountOf(ctx.spend.amountSats)}payment from main funds.`,
        ["laptop"],
        ctx.compromiseActive ? "bad" : "neutral",
        {
          ...(ctx.compromiseActive
            ? ATTACK
            : { chapter: "payment" as const, visual: ctx.signerCheating ? ("signer" as const) : undefined }),
          why: "It can't sign it. Main funds only move with your Ledger's approval.",
        },
      );
    case "funding_confirmed":
      return cap(
        `The ${amountOf(ctx.satchel.budgetSats)}funding is sent and confirmed in a block.`,
        ["laptop", "network"],
        "neutral",
        {
          ...satchelStep("funding_confirmed"),
          why: "Main funds paid exactly the approved amount into the satchel, plus a small network fee.",
        },
      );
    case "broadcast":
      if (ctx.flow === "grant") return null;
      return cap(
        "Your laptop sends the verified payment to the Bitcoin network.",
        ["laptop", "network"],
        "good",
        { chapter: "payment" },
      );
    default:
      return null;
  }
}

function vaultEvent(event: XrayEvent, ctx: StoryContext): Caption | null {
  const p = event.payload ?? {};
  switch (event.type) {
    case "satchel_reserved": {
      const path = str(p.path);
      return cap("The vault creates a fresh key for a new satchel.", ["vault", "laptop"], "neutral", {
        ...satchelStep("satchel_reserved"),
        why: `${path ? `Fully hardened path ${path}. ` : ""}This key can only unlock the satchel. Leaking it reveals no other key, and there's no xpub to leak.`,
      });
    }
    case "satchel_funding_released":
      return cap(
        "The vault checks your signature and the plan, then releases one-time keys.",
        ["vault", "laptop"],
        "good",
        {
          ...satchelStep("satchel_funding_released"),
          why: "Only the keys for the coins being spent, never the seed. On real hardware they reach the signer by QR; this demo relays them through the laptop.",
        },
      );
    case "satchel_released":
      return cap("The vault hands over the satchel key.", ["vault", "laptop"], "good", {
        ...satchelStep("satchel_released"),
        why: "Only after checking proof that this exact, verified funding is in a block.",
      });
    case "spend_keys_released":
      return cap(
        "The vault checks your signature and releases one-time keys for this payment only.",
        ["vault", "laptop"],
        ctx.compromiseActive ? "bad" : "good",
        {
          chapter: "payment",
          visual: ctx.signerCheating ? "signer" : undefined,
          why: "Even a rigged signer only ever sees these child keys, never the seed, so it can't empty the wallet.",
        },
      );
    case "release_refused":
      return cap("The vault refused to release any keys.", ["vault"], "bad");
    case "verification_passed":
      return cap("The vault checks the signer's signature: it matches.", ["signer", "vault"], "good", {
        ...(ctx.flow === "grant" ? satchelStep("verification_passed") : { chapter: "payment" as const }),
        why: "Honest signatures are deterministic (RFC 6979), so the vault recomputes every byte. A signer hiding secrets in its signatures would be caught here.",
      });
    case "verification_failed":
      return cap(
        "Vault blocked the transaction: the signer's signature didn't match. Nothing was sent.",
        ["signer", "vault"],
        "bad",
        {
          chapter: "signer",
          visual: "signer",
          moment: "blocked",
          why: "The vault recomputed the honest signature and compared it byte for byte. Nothing reached the network, so nothing leaked.",
        },
      );
    default:
      return null;
  }
}

function signerEvent(event: XrayEvent, ctx: StoryContext): Caption | null {
  const p = event.payload ?? {};
  switch (event.type) {
    case "psbt_signed":
      if (p.nonce === "random") {
        return cap("The signer signs it, but not the honest way.", ["laptop", "signer"], "bad", {
          chapter: "signer",
          visual: "signer",
          simulation: true,
          why: "It used its own nonces, not the honest RFC 6979 ones. Rigged nonces look just as random: that's how Dark Skippy hides your secrets.",
        });
      }
      return cap("The offline signer signs it with those one-time keys.", ["laptop", "signer"], "neutral", {
        ...(ctx.flow === "grant" ? satchelStep("psbt_signed") : { chapter: "payment" as const }),
        why: "The signer is treated as possibly malicious. It never sees the seed, only the child keys for this one payment.",
      });
    case "random_nonce_enabled":
      return cap("Simulated attack: the signer is rigged.", ["signer"], "bad", {
        chapter: "signer",
        visual: "signer",
        simulation: true,
        why: "What if the signing hardware is malicious? It can hide your seed in the secret nonces of just two signatures. That's the Dark Skippy attack.",
      });
    case "random_nonce_disabled":
      return cap("Demo: the signer is honest again.", ["signer"]);
    case "sign_refused":
      return cap("The signer refused to sign.", ["signer"]);
    default:
      return null;
  }
}

function marketplaceEvent(event: XrayEvent): Caption | null {
  if (event.type === "order_paid") {
    return cap("The payment confirmed. Your order is paid.", ["network"], "good", {
      chapter: "shopping",
      visual: "store",
    });
  }
  return null;
}

/** The step for an event (headline, why, chapter, visual), or null if silent. */
export function captionFor(event: XrayEvent, ctx: StoryContext): Caption | null {
  if (isSilent(event)) return null;
  switch (event.component) {
    case "agent":
      return agentEvent(event, ctx);
    case "approver":
      return approverEvent(event, ctx);
    case "laptop":
      return laptopEvent(event, ctx);
    case "vault":
      return vaultEvent(event, ctx);
    case "signer":
      return signerEvent(event, ctx);
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
