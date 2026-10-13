import { usdFromDollars } from "./money.ts";

export interface Product {
  id: string;
  name: string;
  seller: string;
  category: string;
  price_usd: number;
  price_btc: string;
  price_sats: number;
  delivery_date: string;
  available: number;
}

export interface OrderInfo {
  orderId: string;
  name: string;
  category: string | null;
  amountUsd: number | null;
  deliveryDate: string | null;
}

export type ApprovalStatus =
  | "pending"
  | "approved"
  | "rejected"
  | "blocked"
  | "failed";

export interface Approval {
  what: "budget" | "purchase";
  status: ApprovalStatus;
  amountUsd: number | null;
  item: string | null;
}

export type Block =
  | { kind: "user"; id: number; text: string }
  | { kind: "assistant"; id: number; text: string }
  | { kind: "cards"; id: number; products: Product[] }
  | { kind: "activity"; id: number; toolId: string; text: string }
  | { kind: "approval"; id: number; toolId: string; approval: Approval }
  | { kind: "order"; id: number; order: OrderInfo }
  | { kind: "retry"; id: number; message: string | null };

export interface ChatEvent {
  type: string;
  [key: string]: unknown;
}

interface PendingTool {
  name: string;
  input: Record<string, unknown>;
}

interface KnownProduct {
  name: string;
  category: string | null;
  deliveryDate: string | null;
}

export interface ChatState {
  sessionId: string | null;
  blocks: Block[];
  busy: boolean;
  nextId: number;
  pending: Record<string, PendingTool>;
  products: Record<string, KnownProduct>;
  lastExceeds: {
    orderId: string;
    productId: string | null;
    amountUsd: number | null;
  } | null;
  lastUserText: string | null;
  /** Raw error text for the developer console; never rendered. */
  lastError: string | null;
}

export const initialChatState: ChatState = {
  sessionId: null,
  blocks: [],
  busy: false,
  nextId: 1,
  pending: {},
  products: {},
  lastExceeds: null,
  lastUserText: null,
  lastError: null,
};

export const MAX_CARDS = 3;

const ACTIVITY_TEXT: Record<string, string> = {
  search_products: "Searching the shop…",
  get_product_details: "Checking details…",
  suggest_products: "Picking options…",
  check_budget: "Checking your budget…",
  buy_product: "Placing your order…",
  check_order: "Checking your order…",
};

const CATEGORY_NOUNS: Record<string, string> = {
  headphones: "headphones",
  laptops: "laptop",
};

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

/** A short name for the item, such as "laptop" for the Featherbook 13. */
export function itemNoun(
  products: Record<string, KnownProduct>,
  productId: string | null,
): string | null {
  if (!productId) return null;
  const known = products[productId];
  if (!known) return humanise(productId);
  return CATEGORY_NOUNS[known.category ?? ""] ?? known.name;
}

export function approvalText(a: Approval): string {
  const amount = a.amountUsd !== null ? usdFromDollars(a.amountUsd) : null;
  const purchase = [amount, a.item ?? "purchase"].filter(Boolean).join(" ");
  const thing =
    a.what === "budget"
      ? `${amount ?? "a"} budget`
      : `${purchase} from main funds`;
  switch (a.status) {
    case "pending":
      return a.what === "budget"
        ? `Needs your approval on Ledger: ${amount ? `a ${amount}` : "a"} budget`
        : `Needs your approval on Ledger: ${thing}`;
    case "approved":
      return `Approved on Ledger: ${thing}`;
    case "rejected":
      return `Rejected on Ledger: ${thing}`;
    case "blocked":
      return `Blocked by your vault: ${purchase}. Nothing was sent.`;
    case "failed":
      return `Didn't go through: ${thing}. Nothing was approved.`;
  }
}

type DistributiveOmit<T, K extends PropertyKey> = T extends unknown
  ? Omit<T, K>
  : never;

function push(state: ChatState, block: DistributiveOmit<Block, "id">): ChatState {
  return {
    ...state,
    blocks: [...state.blocks, { ...block, id: state.nextId } as Block],
    nextId: state.nextId + 1,
  };
}

function dropActivity(state: ChatState, toolId: string): ChatState {
  return {
    ...state,
    blocks: state.blocks.filter(
      (b) => !(b.kind === "activity" && b.toolId === toolId),
    ),
  };
}

function updateApproval(
  state: ChatState,
  toolId: string,
  patch: Partial<Approval>,
): ChatState {
  return {
    ...state,
    blocks: state.blocks.map((b) =>
      b.kind === "approval" && b.toolId === toolId
        ? { ...b, approval: { ...b.approval, ...patch } }
        : b,
    ),
  };
}

function learnProduct(
  products: Record<string, KnownProduct>,
  raw: unknown,
): Record<string, KnownProduct> {
  if (!raw || typeof raw !== "object") return products;
  const p = raw as Record<string, unknown>;
  const id = str(p.id);
  const name = str(p.name);
  if (!id || !name) return products;
  return {
    ...products,
    [id]: {
      name,
      category: str(p.category),
      deliveryDate: str(p.delivery_date),
    },
  };
}

export function sendUserMessage(state: ChatState, text: string): ChatState {
  const cleared = {
    ...state,
    blocks: state.blocks.filter((b) => b.kind !== "retry"),
  };
  return {
    ...push(cleared, { kind: "user", text }),
    busy: true,
    lastUserText: text,
  };
}

function toolResult(state: ChatState, event: ChatEvent): ChatState {
  const id = event.id as string;
  const pending = state.pending[id];
  const result = (event.result ?? {}) as Record<string, unknown>;
  const { [id]: _done, ...rest } = state.pending;
  let next: ChatState = { ...dropActivity(state, id), pending: rest };
  const name = (event.name as string) || pending?.name;

  if (result.error) {
    next = { ...next, lastError: `${name}: ${String(result.error)}` };
    if (name === "request_budget" || name === "request_large_purchase") {
      next = updateApproval(next, id, { status: "failed" });
    }
    return next;
  }

  switch (name) {
    case "search_products": {
      let products = next.products;
      for (const r of (result.results ?? []) as Record<string, unknown>[]) {
        products = learnProduct(products, r?.listing);
      }
      return { ...next, products };
    }
    case "get_product_details":
      return { ...next, products: learnProduct(next.products, result.listing) };
    case "suggest_products": {
      const products = ((result.products ?? []) as Record<string, unknown>[])
        .filter((p) => p && !("error" in p))
        .map((p) => p as unknown as Product);
      let known = next.products;
      for (const p of products) known = learnProduct(known, p);
      next = { ...next, products: known };
      if (products.length === 0) return next;
      return push(next, { kind: "cards", products: products.slice(0, MAX_CARDS) });
    }
    case "request_budget": {
      if (result.granted) {
        const sats = num(result.budget_sats);
        return updateApproval(next, id, {
          status: "approved",
          amountUsd:
            num(result.budget_usd) ?? (sats !== null ? sats / 1000 : null),
        });
      }
      const reason = String(result.reason ?? "");
      return updateApproval(next, id, {
        status: /reject/i.test(reason) ? "rejected" : "failed",
      });
    }
    case "buy_product": {
      const productId = str(pending?.input?.product_id);
      if (result.status === "exceeds_budget") {
        return {
          ...next,
          lastExceeds: {
            orderId: result.order_id as string,
            productId,
            amountUsd: num(result.amount_usd),
          },
        };
      }
      if (result.status === "paid_from_budget") {
        const known = productId ? next.products[productId] : undefined;
        return push(next, {
          kind: "order",
          order: {
            orderId: result.order_id as string,
            name: str(result.product) ?? known?.name ?? "Your order",
            category: known?.category ?? null,
            amountUsd: num(result.amount_usd),
            deliveryDate: str(result.delivery_date) ?? known?.deliveryDate ?? null,
          },
        });
      }
      return next;
    }
    case "request_large_purchase": {
      if (result.paid) {
        next = updateApproval(next, id, { status: "approved" });
        const exceeds = next.lastExceeds;
        const known = exceeds?.productId
          ? next.products[exceeds.productId]
          : undefined;
        return push(next, {
          kind: "order",
          order: {
            orderId: str(pending?.input?.order_id) ?? exceeds?.orderId ?? "",
            name:
              known?.name ??
              (exceeds?.productId ? humanise(exceeds.productId) : "Your order"),
            category: known?.category ?? null,
            amountUsd: exceeds?.amountUsd ?? null,
            deliveryDate: known?.deliveryDate ?? null,
          },
        });
      }
      if (result.stage === "verification") {
        return updateApproval(next, id, { status: "blocked" });
      }
      const reason = String(result.reason ?? "");
      return updateApproval(next, id, {
        status:
          result.stage === "approval" && /reject/i.test(reason)
            ? "rejected"
            : "failed",
      });
    }
    default:
      return next;
  }
}

export function reduce(state: ChatState, event: ChatEvent): ChatState {
  switch (event.type) {
    case "session":
      return { ...state, sessionId: event.session_id as string };
    case "text": {
      const last = state.blocks[state.blocks.length - 1];
      if (last && last.kind === "assistant") {
        const blocks = state.blocks.slice(0, -1);
        blocks.push({ ...last, text: last.text + (event.delta as string) });
        return { ...state, blocks };
      }
      return push(state, { kind: "assistant", text: event.delta as string });
    }
    case "notice":
      return state;
    case "tool_call": {
      const id = event.id as string;
      const name = event.name as string;
      const input = (event.input ?? {}) as Record<string, unknown>;
      const next: ChatState = {
        ...state,
        pending: { ...state.pending, [id]: { name, input } },
      };
      if (name === "request_budget") {
        return push(next, {
          kind: "approval",
          toolId: id,
          approval: {
            what: "budget",
            status: "pending",
            amountUsd: num(input.amount_usd),
            item: null,
          },
        });
      }
      if (name === "request_large_purchase") {
        const exceeds = state.lastExceeds;
        return push(next, {
          kind: "approval",
          toolId: id,
          approval: {
            what: "purchase",
            status: "pending",
            amountUsd: exceeds?.amountUsd ?? null,
            item: itemNoun(state.products, exceeds?.productId ?? null),
          },
        });
      }
      if (ACTIVITY_TEXT[name]) {
        return push(next, { kind: "activity", toolId: id, text: ACTIVITY_TEXT[name] });
      }
      return next;
    }
    case "tool_result":
      return toolResult(state, event);
    case "error": {
      const failed = state.blocks.map((b) =>
        b.kind === "approval" && b.approval.status === "pending"
          ? { ...b, approval: { ...b.approval, status: "failed" as const } }
          : b,
      );
      return push(
        {
          ...state,
          blocks: failed.filter((b) => b.kind !== "activity"),
          busy: false,
          pending: {},
          lastError: String(event.error ?? "unknown error"),
        },
        { kind: "retry", message: state.lastUserText },
      );
    }
    case "done":
      return {
        ...state,
        busy: false,
        blocks: state.blocks.filter((b) => b.kind !== "activity"),
      };
    default:
      return state;
  }
}
