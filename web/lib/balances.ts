import type { XrayState } from "./api.ts";
import type { XrayEvent } from "./xray.ts";

export interface BudgetView {
  remainingSats: number;
  budgetSats: number;
}

function num(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function time(ts: string | undefined): number {
  const parsed = ts ? Date.parse(ts) : NaN;
  return Number.isFinite(parsed) ? parsed : 0;
}

/** The agent behind a chat session, read from the agent's own tool events. */
export function agentIdForSession(
  events: XrayEvent[],
  sessionId: string | null,
): string | null {
  if (!sessionId) return null;
  for (const e of events) {
    const p = e.payload ?? {};
    if (p.session_id === sessionId && typeof p.agent_id === "string") {
      return p.agent_id;
    }
  }
  return null;
}

function lastPayment(
  events: XrayEvent[],
  envelopeIndex: number,
): XrayEvent | null {
  for (let i = events.length - 1; i >= 0; i--) {
    const e = events[i];
    if (
      e.component === "agent" &&
      e.type === "payment_sent" &&
      e.payload?.envelope_index === envelopeIndex
    ) {
      return e;
    }
  }
  return null;
}

/**
 * How much of an agent's budget is left. Chain state only counts confirmed
 * coins, so while a payment is unconfirmed the change it created is the
 * remaining budget.
 */
export function budgetFor(
  state: XrayState | null,
  events: XrayEvent[],
  agentId: string | null,
): BudgetView | null {
  if (!agentId) return null;
  const envelope = state?.envelopes?.find((e) => e.assigned_to === agentId);
  let index: number | null = envelope?.index ?? null;
  let budget: number | null = envelope?.budget_sats ?? null;
  if (envelope == null) {
    for (let i = events.length - 1; i >= 0; i--) {
      const e = events[i];
      if (e.type === "wallet_loaded" && e.payload?.agent_id === agentId) {
        index = num(e.payload?.envelope_index);
        budget = num(e.payload?.budget_sats);
        break;
      }
    }
  }
  if (index === null || budget === null) return null;

  const payment = lastPayment(events, index);
  const change = num(payment?.payload?.change_sats);
  if (envelope == null) {
    return { remainingSats: change ?? budget, budgetSats: budget };
  }
  const confirmed = envelope.balance_sats ?? 0;
  const available = envelope.available_sats ?? confirmed;
  const unconfirmedSpend = available < confirmed;
  const newerThanState =
    payment != null && time(payment.ts) > time(state?.ts);
  if (change !== null && (unconfirmedSpend || newerThanState)) {
    return { remainingSats: change, budgetSats: budget };
  }
  return { remainingSats: available, budgetSats: budget };
}

/** True once the simulated compromise has started in this run. */
export function attackSeen(events: XrayEvent[]): boolean {
  return events.some((e) => e.type === "compromise_started");
}

/**
 * What the attacker has taken: the loss-sink wallet, or what the drain events
 * report if they arrived before the next state refresh.
 */
export function lostToAttacker(
  state: XrayState | null,
  events: XrayEvent[],
): number {
  const sink = state?.loss_sink;
  const onChain = sink
    ? (sink.confirmed_sats ?? 0) + (sink.pending_sats ?? 0)
    : 0;
  let drained = 0;
  for (const e of events) {
    if (e.type === "compromise_envelope_drained") {
      drained += num(e.payload?.amount_sats) ?? 0;
    }
  }
  return Math.max(onChain, drained);
}

export function mainFunds(state: XrayState | null): number | null {
  return state?.main_funds?.balance_sats ?? null;
}

export interface StoryNumbers {
  mainFundsSats: number | null;
  budget: BudgetView | null;
  lostSats: number;
  showLost: boolean;
}

/**
 * The figures as of the step on screen. Once the story has caught up these
 * are the live numbers (the same as the chat's pill); while a presenter is
 * still walking through earlier steps they show what was true then, so a
 * balance never changes before the step that explains it.
 */
export function storyNumbers(
  state: XrayState | null,
  events: XrayEvent[],
  agentId: string | null,
  playheadSeq: number,
  caughtUp: boolean,
): StoryNumbers {
  if (caughtUp) {
    const lost = lostToAttacker(state, events);
    return {
      mainFundsSats: mainFunds(state),
      budget: budgetFor(state, events, agentId),
      lostSats: lost,
      showLost: attackSeen(events) || lost > 0,
    };
  }
  let main = mainFunds(state);
  let reserved = 0;
  let loaded: { index: number; budget: number } | null = null;
  let change: number | null = null;
  let drained = 0;
  let attack = false;
  for (const e of events) {
    const p = e.payload ?? {};
    if (e.component === "vault" && e.type === "satchel_reserved") {
      reserved = num(p.budget_sats) ?? 0;
    }
    if (e.seq > playheadSeq) {
      // Satchel fundings the story hasn't reached yet are still in main funds.
      if (
        e.component === "laptop" &&
        e.type === "funding_confirmed" &&
        main !== null &&
        time(state?.ts) > time(e.ts)
      ) {
        main += reserved;
      }
      continue;
    }
    if (e.type === "wallet_loaded" && agentId && p.agent_id === agentId) {
      const index = num(p.envelope_index);
      const budget = num(p.budget_sats);
      if (index !== null && budget !== null) {
        loaded = { index, budget };
        change = null;
      }
    }
    if (
      e.type === "payment_sent" &&
      loaded &&
      p.envelope_index === loaded.index
    ) {
      change = num(p.change_sats);
    }
    if (e.type === "compromise_started") attack = true;
    if (e.type === "compromise_envelope_drained") drained += num(p.amount_sats) ?? 0;
  }
  return {
    mainFundsSats: main,
    budget: loaded
      ? { remainingSats: change ?? loaded.budget, budgetSats: loaded.budget }
      : null,
    lostSats: drained,
    showLost: attack || drained > 0,
  };
}
