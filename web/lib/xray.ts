export interface XrayEvent {
  seq: number;
  id: string;
  ts: string;
  component: string;
  type: string;
  message: string;
  payload: Record<string, unknown> | null;
  nodes?: { from?: string; to?: string; at?: string };
  label?: string;
  qr?: { type: string; parts: string[]; redacted: boolean };
  alert?: { level: string; title: string; reasons?: string[] };
  simulation?: boolean;
  boot?: string;
}

export const NODE_IDS = [
  "agent",
  "envelope",
  "laptop",
  "ledger",
  "vault",
  "signer",
  "marketplace",
  "losssink",
] as const;

export type NodeId = (typeof NODE_IDS)[number];

export const NODE_LABELS: Record<NodeId, string> = {
  agent: "Agent",
  envelope: "Envelope",
  laptop: "Laptop",
  ledger: "Ledger",
  vault: "Vault",
  signer: "Signer",
  marketplace: "Marketplace",
  losssink: "Loss sink",
};

export interface EventAnimation {
  glow: string[];
  edge: { from: string; to: string } | null;
}

export function eventAnimation(event: XrayEvent): EventAnimation {
  const nodes = event.nodes;
  if (!nodes) return { glow: [], edge: null };
  if (nodes.at) {
    return { glow: [nodes.at], edge: null };
  }
  if (nodes.from && nodes.to) {
    return {
      glow: [nodes.from, nodes.to],
      edge: { from: nodes.from, to: nodes.to },
    };
  }
  return { glow: [], edge: null };
}

export function feedLabel(event: XrayEvent): string {
  return event.label ?? event.message;
}

export function feedTime(ts: string): string {
  const parsed = new Date(ts);
  if (Number.isNaN(parsed.getTime())) return ts;
  return parsed.toLocaleTimeString("en-GB", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

export const COMPONENT_COLORS: Record<string, string> = {
  agent: "bg-violet-100 text-violet-800",
  laptop: "bg-sky-100 text-sky-800",
  approver: "bg-emerald-100 text-emerald-800",
  vault: "bg-amber-100 text-amber-800",
  signer: "bg-orange-100 text-orange-800",
  marketplace: "bg-teal-100 text-teal-800",
};

export function componentColor(component: string): string {
  return COMPONENT_COLORS[component] ?? "bg-neutral-100 text-neutral-700";
}
