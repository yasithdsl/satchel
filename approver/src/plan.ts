import { randomBytes } from "node:crypto";

const NAME_RE = /^[A-Za-z0-9][A-Za-z0-9 ._-]{0,31}$/;
const DESTINATION_RE = /^bcrt1[02-9ac-hj-np-z]{8,87}$/;
const HASH_RE = /^[0-9a-f]{64}$/;
const NONCE_RE = /^[0-9a-f]{16}$/;
const MAX_SATS = 2_100_000_000_000_000;
const MONTHS = [
  "Jan", "Feb", "Mar", "Apr", "May", "Jun",
  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
] as const;

/** Fund a fresh satchel from main funds and hand its key to the agent. */
export type SatchelGrantPlan = {
  kind: "satchel_grant";
  satchel_index: number;
  agent_id: string;
  budget_sats: number;
  expires_at: number;
  psbt_sha256: string;
};

export type LargeSpendPlan = {
  kind: "large_spend";
  amount_sats: number;
  destination: string;
  purpose: string;
  psbt_sha256: string;
};

export type Plan = SatchelGrantPlan | LargeSpendPlan;

const SATCHEL_KEYS = [
  "kind",
  "satchel_index",
  "agent_id",
  "budget_sats",
  "expires_at",
  "psbt_sha256",
];
const SPEND_KEYS = [
  "kind",
  "amount_sats",
  "destination",
  "purpose",
  "psbt_sha256",
];

function checkKeys(plan: Record<string, unknown>, wanted: string[]): void {
  const keys = Object.keys(plan);
  for (const key of wanted) {
    if (!(key in plan)) throw new Error(`plan is missing '${key}'`);
  }
  for (const key of keys) {
    if (!wanted.includes(key)) throw new Error(`plan has unexpected key '${key}'`);
  }
}

function checkInt(value: unknown, name: string): number {
  if (typeof value !== "number" || !Number.isInteger(value)) {
    throw new Error(`${name} must be an integer`);
  }
  return value;
}

function checkSats(value: unknown, name: string): number {
  const n = checkInt(value, name);
  if (n < 1 || n > MAX_SATS) {
    throw new Error(`${name} must be in 1..${MAX_SATS}`);
  }
  return n;
}

function checkName(value: unknown, name: string): string {
  if (typeof value !== "string" || !NAME_RE.test(value)) {
    throw new Error(`${name} must match ${NAME_RE}`);
  }
  return value;
}

export function validatePlan(plan: unknown): Plan {
  if (typeof plan !== "object" || plan === null || Array.isArray(plan)) {
    throw new Error("plan must be a JSON object");
  }
  const obj = plan as Record<string, unknown>;
  if (obj.kind === "satchel_grant") {
    checkKeys(obj, SATCHEL_KEYS);
    const satchel_index = checkInt(obj.satchel_index, "satchel_index");
    if (satchel_index < 0 || satchel_index > 2 ** 31 - 1) {
      throw new Error("satchel_index must be in 0..2^31-1");
    }
    const expires_at = checkInt(obj.expires_at, "expires_at");
    if (expires_at <= 0 || expires_at % 60 !== 0) {
      throw new Error("expires_at must be a positive multiple of 60");
    }
    if (expires_at > 253_402_300_740) {
      throw new Error("expires_at must be <= 253402300740");
    }
    const psbt_sha256 = obj.psbt_sha256;
    if (typeof psbt_sha256 !== "string" || !HASH_RE.test(psbt_sha256)) {
      throw new Error("psbt_sha256 must be 64 lowercase hex chars");
    }
    return {
      kind: "satchel_grant",
      satchel_index,
      agent_id: checkName(obj.agent_id, "agent_id"),
      budget_sats: checkSats(obj.budget_sats, "budget_sats"),
      expires_at,
      psbt_sha256,
    };
  }
  if (obj.kind === "large_spend") {
    checkKeys(obj, SPEND_KEYS);
    const destination = obj.destination;
    if (typeof destination !== "string" || !DESTINATION_RE.test(destination)) {
      throw new Error("destination must be a regtest bech32 address");
    }
    const psbt_sha256 = obj.psbt_sha256;
    if (typeof psbt_sha256 !== "string" || !HASH_RE.test(psbt_sha256)) {
      throw new Error("psbt_sha256 must be 64 lowercase hex chars");
    }
    return {
      kind: "large_spend",
      amount_sats: checkSats(obj.amount_sats, "amount_sats"),
      destination,
      purpose: checkName(obj.purpose, "purpose"),
      psbt_sha256,
    };
  }
  throw new Error(`unknown plan kind: ${String(obj.kind)}`);
}

export function newNonce(): string {
  return randomBytes(8).toString("hex");
}

export function checkNonce(nonce: unknown): string {
  if (typeof nonce !== "string" || !NONCE_RE.test(nonce)) {
    throw new Error("nonce must be 16 lowercase hex chars");
  }
  return nonce;
}

function btcAmount(sats: number): string {
  const s = BigInt(sats);
  const whole = s / 100_000_000n;
  let frac = (s % 100_000_000n).toString().padStart(8, "0");
  frac = frac.replace(/0+$/, "");
  return frac === "" ? whole.toString() : `${whole}.${frac}`;
}

function expiryText(unix: number): string {
  const d = new Date(unix * 1000);
  const day = d.getUTCDate().toString().padStart(2, "0");
  const hh = d.getUTCHours().toString().padStart(2, "0");
  const mm = d.getUTCMinutes().toString().padStart(2, "0");
  return `${day} ${MONTHS[d.getUTCMonth()]} ${hh}:${mm} UTC`;
}

/**
 * The exact text the Ledger shows and signs; must match the vault's
 * render_text (fixtures/approval_text_vectors.json). The destination is shown
 * in full so a look-alike address can't reuse the signature.
 */
export function renderText(plan: Plan, nonce: string): string {
  checkNonce(nonce);
  if (plan.kind === "satchel_grant") {
    // One approval covers both: fund the satchel from main funds and hand its
    // key to the agent. The deadline is for that handover only.
    return (
      `Create a ${btcAmount(plan.budget_sats)} BTC satchel ` +
      `#${plan.satchel_index} for ${plan.agent_id} from main funds. ` +
      `Approval valid until ${expiryText(plan.expires_at)}. Nonce ${nonce}`
    );
  }
  return (
    `Pay ${btcAmount(plan.amount_sats)} BTC to ${plan.destination} ` +
    `for ${plan.purpose}. Nonce ${nonce}`
  );
}
