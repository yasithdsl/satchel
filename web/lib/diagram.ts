import type { XrayState } from "./api.ts";
import type { NodeId } from "./xray.ts";
import { satsToUsd } from "./story.ts";

export interface NodeSpec {
  id: NodeId;
  name: string;
  role: string;
  x: number;
  y: number;
}

export interface Zone {
  id: string;
  label: string;
  tone: "neutral" | "warn" | "danger";
  left: number;
  top: number;
  width: number;
  height: number;
}

export const ZONES: Zone[] = [
  {
    id: "online",
    label: "Online",
    tone: "neutral",
    left: 1,
    top: 1,
    width: 37,
    height: 98,
  },
  {
    id: "you",
    label: "You",
    tone: "warn",
    left: 55,
    top: 1,
    width: 44,
    height: 27,
  },
  {
    id: "airgap",
    label: "Air-gapped",
    tone: "neutral",
    left: 55,
    top: 32,
    width: 44,
    height: 37,
  },
  {
    id: "attacker",
    label: "Attacker · simulation",
    tone: "danger",
    left: 55,
    top: 73,
    width: 44,
    height: 26,
  },
];

export const NODES: NodeSpec[] = [
  { id: "agent", name: "Agent", role: "Your shopping assistant", x: 19, y: 16 },
  { id: "envelope", name: "Envelope", role: "Prepaid budget", x: 19, y: 41 },
  { id: "laptop", name: "Laptop", role: "Carries payloads, holds no keys", x: 19, y: 66 },
  { id: "marketplace", name: "Shop", role: "Demo marketplace", x: 19, y: 90 },
  { id: "ledger", name: "Ledger", role: "You approve here", x: 77, y: 15 },
  { id: "vault", name: "Vault", role: "Holds the seed · never signs · checks signatures", x: 66, y: 51 },
  { id: "signer", name: "Signer", role: "Signs with one-time keys", x: 89, y: 51 },
  { id: "losssink", name: "Loss sink", role: "Attacker wallet", x: 77, y: 86 },
];

export const NODE_POS: Record<NodeId, { x: number; y: number }> =
  Object.fromEntries(
    NODES.map((n) => [n.id, { x: n.x, y: n.y }]),
  ) as Record<NodeId, { x: number; y: number }>;

export const EDGES: [NodeId, NodeId][] = [
  ["agent", "envelope"],
  ["agent", "laptop"],
  ["agent", "marketplace"],
  ["envelope", "laptop"],
  ["envelope", "marketplace"],
  ["envelope", "losssink"],
  ["laptop", "ledger"],
  ["laptop", "vault"],
  ["laptop", "signer"],
  ["laptop", "marketplace"],
];

export function nodeValue(id: NodeId, state: XrayState | null): string | null {
  if (!state) return null;
  switch (id) {
    case "envelope": {
      const envelopes = state.envelopes ?? [];
      const active =
        envelopes.find((e) => e.assigned_to) ??
        envelopes.find((e) => e.status === "active");
      if (!active) return "none assigned yet";
      const remaining = active.available_sats ?? active.balance_sats;
      return remaining === null || remaining === undefined
        ? null
        : `${satsToUsd(remaining)} left of ${satsToUsd(active.budget_sats)}`;
    }
    case "vault": {
      const sats = state.main_funds?.balance_sats;
      return sats === null || sats === undefined
        ? null
        : `${satsToUsd(sats)} main funds`;
    }
    case "losssink": {
      const sink = state.loss_sink;
      if (!sink) return "$0 captured";
      const total = (sink.confirmed_sats ?? 0) + (sink.pending_sats ?? 0);
      return `${satsToUsd(total)} captured`;
    }
    case "signer":
      return state.random_nonce_signer ? "random nonce ON" : null;
    case "ledger": {
      const pending = state.pending_approval?.pending;
      return pending ? "approval waiting" : "idle";
    }
    default:
      return null;
  }
}
