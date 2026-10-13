import type { StripNode } from "./caption.ts";
import type { XrayEvent } from "./xray.ts";

export interface StripNodeSpec {
  id: StripNode;
  name: string;
  /** The name in the slim strip above a stage panel, when `name` is too long. */
  short?: string;
  line: string;
}

export interface StripZone {
  id: "online" | "you" | "offline" | "network";
  label: string;
  nodes: StripNode[];
}

export const STRIP_NODES: Record<StripNode, StripNodeSpec> = {
  agent: { id: "agent", name: "Agent", line: "Spends only its satchel" },
  laptop: { id: "laptop", name: "Laptop", line: "Carries messages, no keys" },
  ledger: { id: "ledger", name: "Ledger", line: "Nothing to approve" },
  vault: { id: "vault", name: "Vault", line: "Holds the seed, never signs" },
  signer: { id: "signer", name: "Signer", line: "Signs with one-time keys" },
  network: { id: "network", name: "Bitcoin network", short: "Bitcoin", line: "Where payments go" },
  attacker: { id: "attacker", name: "Attacker", line: "Simulated thief" },
};

export function stripZones(showAttacker: boolean): StripZone[] {
  return [
    { id: "online", label: "Online", nodes: ["agent", "laptop"] },
    { id: "you", label: "You", nodes: ["ledger"] },
    { id: "offline", label: "Offline", nodes: ["vault", "signer"] },
    {
      id: "network",
      label: "Network",
      nodes: showAttacker ? ["network", "attacker"] : ["network"],
    },
  ];
}

/**
 * The attacker node belongs to the compromise scene only: it appears when the
 * simulation starts and leaves once the next scene begins.
 */
export function attackerVisible(events: XrayEvent[]): boolean {
  let started = -1;
  for (let i = events.length - 1; i >= 0; i--) {
    if (events[i].type === "compromise_started") {
      started = i;
      break;
    }
  }
  if (started === -1) return false;
  let finished = false;
  for (let i = started + 1; i < events.length; i++) {
    const e = events[i];
    if (e.type === "compromise_finished") finished = true;
    if (
      finished &&
      (e.type === "random_nonce_enabled" ||
        (e.type === "tool_call" && e.payload?.tool === "request_budget"))
    ) {
      return false;
    }
  }
  return true;
}
