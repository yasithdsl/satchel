import type { XrayEvent } from "./xray.ts";

export type GuideActionKind =
  | "send"
  | "mine"
  | "compromise"
  | "random-on"
  | "random-off"
  | "device";

export interface GuideAction {
  kind: GuideActionKind;
  label: string;
  message?: string;
}

export interface GuideStep {
  id: string;
  text: string;
  action?: GuideAction;
  matches?: (e: XrayEvent) => boolean;
  auto?: boolean;
}

export interface GuideScenario {
  id: string;
  title: string;
  intro: string;
  steps: GuideStep[];
}

function toolCall(name: string): (e: XrayEvent) => boolean {
  return (e) =>
    e.component === "agent" &&
    e.type === "tool_call" &&
    e.payload?.tool === name;
}

function isType(
  component: string,
  ...types: string[]
): (e: XrayEvent) => boolean {
  return (e) =>
    e.component === component && types.includes(e.type);
}

export const SCENARIOS: GuideScenario[] = [
  {
    id: "purchase",
    title: "1 · Everyday purchase",
    intro:
      "Ask for a prepaid budget, approve it on the Ledger, and let the agent pay inside it.",
    steps: [
      {
        id: "ask",
        text: "Ask the agent for headphones",
        action: {
          kind: "send",
          label: "Send for me",
          message:
            "Find me headphones under $200 that arrive by Friday.",
        },
        matches: toolCall("request_budget"),
      },
      {
        id: "approve-budget",
        text: "Approve the $200 budget on the Ledger",
        action: { kind: "device", label: "Show the Ledger" },
        matches: isType("vault", "envelope_released"),
      },
      {
        id: "buy",
        text: "Buy the Aurora headphones",
        action: {
          kind: "send",
          label: "Send for me",
          message: "Buy the Aurora ANC Wireless Headphones.",
        },
        matches: (e) =>
          e.component === "agent" &&
          e.type === "payment_sent" &&
          e.nodes?.to !== "losssink",
      },
      {
        id: "mine",
        text: "Mine a block so the shop confirms the payment",
        action: { kind: "mine", label: "Mine a block" },
        matches: isType("marketplace", "order_paid"),
      },
    ],
  },
  {
    id: "compromise",
    title: "2 · Compromised agent (simulation)",
    intro:
      "An attacker takes over the agent. The envelope is the most it can lose — your Ledger still guards the main funds.",
    steps: [
      {
        id: "mine-first",
        text: "Mine a block so the envelope's change confirms",
        action: { kind: "mine", label: "Mine a block" },
        matches: isType("network", "block_mined"),
      },
      {
        id: "compromise",
        text: "Simulate the compromised agent",
        action: {
          kind: "compromise",
          label: "Start the simulation",
        },
        matches: isType(
          "agent",
          "compromise_envelope_drained",
          "compromise_envelope_empty",
        ),
      },
      {
        id: "reject",
        text: "Reject the attacker's main-funds request on the Ledger",
        action: { kind: "device", label: "Show the Ledger" },
        matches: isType("agent", "compromise_large_spend_blocked"),
      },
      {
        id: "result",
        text: "The loss stayed inside the envelope",
        auto: true,
      },
    ],
  },
  {
    id: "malicious-signer",
    title: "3 · Malicious signer (simulation)",
    intro:
      "The signer is trusted with one-time keys, never the seed. Here it cheats with random nonces — the vault catches it.",
    steps: [
      {
        id: "random-on",
        text: "Turn on the malicious signer",
        action: { kind: "random-on", label: "Turn it on" },
        matches: isType("signer", "random_nonce_enabled"),
      },
      {
        id: "ask-laptop",
        text: "Ask for the Featherbook laptop",
        action: {
          kind: "send",
          label: "Send for me",
          message: "Buy me the Featherbook 13 laptop.",
        },
        matches: isType("agent", "large_purchase_notice"),
      },
      {
        id: "approve-spend",
        text: "Approve the purchase on the Ledger",
        action: { kind: "device", label: "Show the Ledger" },
        matches: isType("vault", "spend_keys_released"),
      },
      {
        id: "blocked",
        text: "Watch the vault block the forged signature",
        matches: isType("vault", "verification_failed"),
      },
      {
        id: "random-off",
        text: "Turn the malicious signer back off",
        action: { kind: "random-off", label: "Turn it off" },
        matches: isType("signer", "random_nonce_disabled"),
      },
    ],
  },
];

export interface GuideProgress {
  scenarioId: string;
  stepIndex: number;
  armedAfter: number;
  done: boolean;
}

export function startScenario(
  scenarioId: string,
  lastSeq: number,
): GuideProgress {
  return { scenarioId, stepIndex: 0, armedAfter: lastSeq, done: false };
}

export function scenarioById(id: string): GuideScenario | undefined {
  return SCENARIOS.find((s) => s.id === id);
}

export function currentStep(
  progress: GuideProgress,
): GuideStep | undefined {
  return scenarioById(progress.scenarioId)?.steps[progress.stepIndex];
}

export function advance(
  progress: GuideProgress,
  event: XrayEvent,
): GuideProgress {
  if (progress.done) return progress;
  const scenario = scenarioById(progress.scenarioId);
  if (!scenario) return progress;
  let next = progress;
  while (next.stepIndex < scenario.steps.length) {
    const step = scenario.steps[next.stepIndex];
    if (step.auto) {
      next = { ...next, stepIndex: next.stepIndex + 1 };
      continue;
    }
    if (
      event.seq > next.armedAfter &&
      step.matches &&
      step.matches(event)
    ) {
      next = {
        ...next,
        stepIndex: next.stepIndex + 1,
        armedAfter: event.seq,
      };
      continue;
    }
    break;
  }
  if (next.stepIndex >= scenario.steps.length) {
    next = { ...next, done: true };
  }
  return next;
}
