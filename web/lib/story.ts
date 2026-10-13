import type { XrayEvent } from "./xray.ts";

export type StoryKind =
  | "agent"
  | "ledger"
  | "vault"
  | "laptop"
  | "signer"
  | "shop"
  | "network"
  | "attack";

export type StoryTone =
  | "neutral"
  | "good"
  | "warn"
  | "bad"
  | "sim";

export interface StoryItem {
  text: string;
  kind: StoryKind;
  tone: StoryTone;
}

export function satsToUsd(sats: number): string {
  if (sats % 1000 === 0) {
    return `$${(sats / 1000).toLocaleString("en-US")}`;
  }
  return `$${(sats / 1000).toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

function num(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value)
    ? value
    : null;
}

function str(value: unknown): string | null {
  return typeof value === "string" && value ? value : null;
}

function item(
  text: string,
  kind: StoryKind,
  tone: StoryTone = "neutral",
): StoryItem {
  return { text, kind, tone };
}

export function storyLine(event: XrayEvent): StoryItem | null {
  const p = event.payload ?? {};
  const tool = str(p.tool);
  const input = (p.input ?? {}) as Record<string, unknown>;

  if (event.type === "tool_call" && event.component === "agent") {
    if (tool === "request_budget") {
      const usd = num(input.amount_usd);
      return item(
        `Agent asked for a $${usd ?? "?"} prepaid budget`,
        "agent",
      );
    }
    if (tool === "search_products") {
      const query = str(input.query) ?? "";
      return item(
        `Agent searched the shop for “${query}”`,
        "agent",
      );
    }
    if (tool === "suggest_products") {
      const ids = Array.isArray(input.product_ids)
        ? input.product_ids
        : [];
      return item(
        `Agent suggested ${ids.length} products`,
        "agent",
      );
    }
    return null;
  }

  if (event.component === "approver") {
    if (event.type === "approval_requested") {
      return item(
        `Your Ledger shows: “${str(p.text) ?? event.message}”`,
        "ledger",
        "warn",
      );
    }
    if (event.type === "approval_granted") {
      return item("You approved on the Ledger", "ledger", "good");
    }
    if (event.type === "approval_rejected") {
      return item("You rejected on the Ledger", "ledger", "warn");
    }
    return null;
  }

  if (event.component === "laptop" && typeof p.flow_id === "string") {
    switch (event.type) {
      case "approval_sent_to_vault":
        return item(
          "Laptop passed your signed approval to the vault",
          "laptop",
        );
      case "key_delivered_to_agent":
        return item(
          "Envelope key handed to the agent (key hidden)",
          "laptop",
        );
      case "psbt_built":
        return item(
          "Laptop built an unsigned transaction from your main funds",
          "laptop",
        );
      case "keys_sent_to_signer":
        return item(
          "Laptop sent the transaction and those keys to the signer",
          "laptop",
        );
      case "broadcast":
        return item(
          "Verified transaction broadcast",
          "laptop",
          "good",
        );
      default:
        return null;
    }
  }

  if (event.component === "vault") {
    switch (event.type) {
      case "envelope_released": {
        const idx = num(p.envelope_index);
        return item(
          `Vault checked your Ledger signature and released envelope #${idx ?? "?"}`,
          "vault",
          "good",
        );
      }
      case "release_refused":
        return item(
          `Vault refused to release keys: ${str(p.reason) ?? event.message}`,
          "vault",
          "bad",
        );
      case "spend_keys_released":
        return item(
          "Vault released signing keys for this payment only",
          "vault",
        );
      case "verification_passed":
        return item(
          "Vault re-checked every signature: all match",
          "vault",
          "good",
        );
      case "verification_failed": {
        const reasons = Array.isArray(p.reasons)
          ? (p.reasons as unknown[])
              .map((r) => str(r))
              .filter(Boolean)
          : [];
        return item(
          `Vault blocked the transaction: ${reasons[0] ?? event.message}`,
          "vault",
          "bad",
        );
      }
      default:
        return null;
    }
  }

  if (event.component === "signer") {
    if (event.type === "psbt_signed") {
      const suffix =
        p.nonce === "random" ? " with random nonces" : "";
      return item(
        `Signer signed the transaction${suffix}`,
        "signer",
      );
    }
    if (event.type === "random_nonce_enabled") {
      return item("Malicious signer mode on (demo)", "signer", "warn");
    }
    if (event.type === "random_nonce_disabled") {
      return item("Malicious signer mode off (demo)", "signer");
    }
    return null;
  }

  if (event.component === "marketplace") {
    if (event.type === "order_created") {
      return item("Shop created an order", "shop");
    }
    if (event.type === "payment_seen") {
      return item(
        "Shop sees the payment, waiting for a block",
        "shop",
      );
    }
    if (event.type === "order_paid") {
      return item("Order paid", "shop", "good");
    }
    return null;
  }

  if (event.component === "network" && event.type === "block_mined") {
    return item("A block was mined", "network");
  }

  if (event.component === "agent") {
    switch (event.type) {
      case "payment_sent": {
        if (event.nodes?.to === "losssink") return null;
        const amount = num(p.amount_sats);
        return item(
          `Agent paid ${amount !== null ? satsToUsd(amount) : "?"} from its envelope`,
          "agent",
          "good",
        );
      }
      case "large_purchase_notice":
        return item(
          "Too big for the envelope: needs your approval on the Ledger",
          "ledger",
          "warn",
        );
      case "compromise_started":
        return item(
          "SIMULATION: an attacker has taken over the agent",
          "attack",
          "sim",
        );
      case "compromise_envelope_drained": {
        const amount = num(p.amount_sats);
        return item(
          `SIMULATION: attacker drained the envelope, ${amount !== null ? satsToUsd(amount) : "?"} sent to the loss sink`,
          "attack",
          "sim",
        );
      }
      case "compromise_envelope_empty":
        return item(
          "SIMULATION: envelope already empty",
          "attack",
          "sim",
        );
      case "compromise_large_spend_requested": {
        const amount = num(p.amount_sats);
        return item(
          `SIMULATION: attacker asked for ${amount !== null ? satsToUsd(amount) : "?"} from your main funds`,
          "attack",
          "sim",
        );
      }
      case "compromise_large_spend_blocked":
        return item(
          "Blocked: the request never got past your Ledger, main funds untouched",
          "attack",
          "good",
        );
      case "compromise_large_spend_approved":
        return item(
          "Approved on the Ledger: main funds moved",
          "attack",
          "bad",
        );
      case "compromise_finished":
        return item(
          "SIMULATION over: the loss stayed within the envelope",
          "attack",
          "sim",
        );
      default:
        return null;
    }
  }

  return null;
}
