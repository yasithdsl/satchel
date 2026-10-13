import type { StripNode } from "./caption.ts";
import type { XrayEvent } from "./xray.ts";

/** Enricher node names (diagram-era) mapped onto the strip. */
const TO_STRIP: Record<string, StripNode> = {
  agent: "agent",
  envelope: "agent",
  laptop: "laptop",
  ledger: "ledger",
  vault: "vault",
  signer: "signer",
  marketplace: "network",
  losssink: "attacker",
};

export function stripNodesOf(event: XrayEvent): StripNode[] {
  const n = event.nodes ?? {};
  return [n.from, n.to, n.at]
    .map((id) => (id ? TO_STRIP[id] : undefined))
    .filter((id): id is StripNode => id !== undefined);
}

/** Boundary payloads (QR-ready), newest first. */
export function payloadEvents(events: XrayEvent[]): XrayEvent[] {
  return events.filter((e) => e.qr && e.qr.parts?.length).reverse();
}

/** The most recent payload that crossed into or out of a device. */
export function latestPayloadFor(
  events: XrayEvent[],
  node: StripNode,
): XrayEvent | null {
  return payloadEvents(events).find((e) => stripNodesOf(e).includes(node)) ?? null;
}

const PAYLOAD_NAMES: Record<string, string> = {
  spend_plan: "Plan for the Ledger",
  ledger_approval: "Signed Ledger approval",
  key_release: "Key release",
  address_export: "Address list",
  unsigned_psbt: "Unsigned transaction",
  signed_tx: "Signed transaction",
  verification_result: "Vault verification",
};

export function payloadName(type: string | undefined): string {
  return (type && PAYLOAD_NAMES[type]) ?? "Payload";
}
