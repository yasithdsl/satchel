/**
 * The three demo scenes and their scripted user messages. Keep the messages in
 * step with scripts/demo_scenarios.py, which plays the same scenes headless.
 */
export interface SceneStep {
  label: string;
  message: string;
}

export interface Scene {
  id: "purchase" | "compromise" | "signer";
  title: string;
  /** Sent in a fresh chat, so each scene gets its own agent and budget. */
  open: SceneStep;
  then: SceneStep[];
  hint: string;
}

/** What the simulated attacker asks for from main funds: $5,000. */
export const ATTACK_REQUEST_SATS = 5_000_000;

export const SCENES: Scene[] = [
  {
    id: "purchase",
    title: "1 · Everyday purchase",
    open: {
      label: "Ask for headphones",
      message: "Find me headphones under $200 that arrive by Friday.",
    },
    then: [{ label: "Buy the Aurora", message: "Buy the Aurora ANC Wireless Headphones." }],
    hint: "Approve the $200 budget, buy, then mine a block.",
  },
  {
    id: "compromise",
    title: "2 · Compromised agent",
    open: { label: "Ask for a $200 budget", message: "Get me a $200 budget for today." },
    then: [],
    hint: "Approve it, simulate the compromised agent, then reject the $5,000 request.",
  },
  {
    id: "signer",
    title: "3 · Malicious signer",
    open: { label: "Ask for a $100 budget", message: "Get me a $100 budget for today." },
    then: [{ label: "Buy the Featherbook 13", message: "Buy me the Featherbook 13 laptop." }],
    hint: "Approve the $100 satchel, then turn the random-nonce signer on and buy the Featherbook 13.",
  },
];
