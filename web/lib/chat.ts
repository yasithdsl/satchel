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

export interface OrderChip {
  orderId: string;
  name: string;
  amountUsd: number | null;
  deliveryDate: string | null;
}

export type Block =
  | { kind: "user"; id: number; text: string }
  | { kind: "assistant"; id: number; text: string }
  | { kind: "cards"; id: number; products: Product[] }
  | { kind: "notice"; id: number; text: string }
  | { kind: "activity"; id: number; toolId: string; text: string }
  | { kind: "ledger_wait"; id: number; toolId: string }
  | { kind: "system"; id: number; text: string }
  | { kind: "order"; id: number; order: OrderChip }
  | { kind: "error"; id: number; text: string };

export interface ChatEvent {
  type: string;
  [key: string]: unknown;
}

interface PendingTool {
  name: string;
  input: Record<string, unknown>;
}

export interface ChatState {
  sessionId: string | null;
  blocks: Block[];
  busy: boolean;
  nextId: number;
  pending: Record<string, PendingTool>;
  lastExceeds: { orderId: string; name: string; amountUsd: number | null } | null;
}

export const initialChatState: ChatState = {
  sessionId: null,
  blocks: [],
  busy: false,
  nextId: 1,
  pending: {},
  lastExceeds: null,
};

const LEDGER_TOOLS = new Set(["request_budget", "request_large_purchase"]);

const ACTIVITY_TEXT: Record<string, string> = {
  search_products: "Searching the shop…",
  get_product_details: "Checking details…",
  suggest_products: "Picking options…",
  check_budget: "Checking your budget…",
  buy_product: "Placing your order…",
  check_order: "Checking your order…",
};

function takeId(state: ChatState): number {
  return state.nextId;
}

function push(state: ChatState, block: Block): ChatState {
  return { ...state, blocks: [...state.blocks, block], nextId: state.nextId + 1 };
}

function dropToolBlock(state: ChatState, toolId: string): ChatState {
  return {
    ...state,
    blocks: state.blocks.filter(
      (b) =>
        !(b.kind === "activity" && b.toolId === toolId) &&
        !(b.kind === "ledger_wait" && b.toolId === toolId),
    ),
  };
}

export function sendUserMessage(state: ChatState, text: string): ChatState {
  const id = takeId(state);
  return {
    ...push(state, { kind: "user", id, text }),
    busy: true,
    lastExceeds: null,
  };
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
      return push(state, {
        kind: "assistant",
        id: takeId(state),
        text: event.delta as string,
      });
    }
    case "notice": {
      const block: Block = {
        kind: "notice",
        id: takeId(state),
        text: event.text as string,
      };
      const lastWait = state.blocks.map((b, i) => [b, i] as const).filter(
        ([b]) => b.kind === "ledger_wait",
      );
      if (lastWait.length > 0) {
        const idx = lastWait[lastWait.length - 1][1];
        const blocks = [...state.blocks];
        blocks.splice(idx, 0, block);
        return { ...state, blocks, nextId: state.nextId + 1 };
      }
      return push(state, block);
    }
    case "tool_call": {
      const id = event.id as string;
      const name = event.name as string;
      const input = (event.input ?? {}) as Record<string, unknown>;
      let next: ChatState = {
        ...state,
        pending: { ...state.pending, [id]: { name, input } },
      };
      if (LEDGER_TOOLS.has(name)) {
        next = push(next, { kind: "ledger_wait", id: takeId(next), toolId: id });
      } else if (ACTIVITY_TEXT[name]) {
        next = push(next, {
          kind: "activity",
          id: takeId(next),
          toolId: id,
          text: ACTIVITY_TEXT[name],
        });
      }
      return next;
    }
    case "tool_result": {
      const id = event.id as string;
      const pending = state.pending[id];
      const result = (event.result ?? {}) as Record<string, unknown>;
      let next = dropToolBlock(state, id);
      const { [id]: _done, ...rest } = next.pending;
      next = { ...next, pending: rest };
      if (result.error) {
        return push(next, {
          kind: "system",
          id: takeId(next),
          text: `Something went wrong (${String(result.error).slice(0, 60)})`,
        });
      }
      const name = (event.name as string) || pending?.name;
      switch (name) {
        case "suggest_products": {
          const products = ((result.products ?? []) as Record<string, unknown>[])
            .filter((p) => p && !("error" in p))
            .map((p) => p as unknown as Product);
          if (products.length === 0) return next;
          return push(next, { kind: "cards", id: takeId(next), products });
        }
        case "request_budget":
          if (result.granted) {
            const usd =
              (result.budget_usd as number) ??
              Math.round(((result.budget_sats as number) ?? 0) / 1000);
            return push(next, {
              kind: "system",
              id: takeId(next),
              text: `$${usd} prepaid budget approved`,
            });
          }
          return push(next, {
            kind: "system",
            id: takeId(next),
            text: "Declined on Ledger",
          });
        case "buy_product":
          if (result.status === "exceeds_budget") {
            return {
              ...next,
              lastExceeds: {
                orderId: result.order_id as string,
                name: (pending?.input?.product_id as string) ?? "item",
                amountUsd: (result.amount_usd as number) ?? null,
              },
            };
          }
          if (result.status === "paid_from_budget") {
            return push(next, {
              kind: "order",
              id: takeId(next),
              order: {
                orderId: result.order_id as string,
                name: (result.product as string) ?? "item",
                amountUsd: (result.amount_usd as number) ?? null,
                deliveryDate: (result.delivery_date as string) ?? null,
              },
            });
          }
          return next;
        case "request_large_purchase":
          if (result.paid) {
            const exceeds = state.lastExceeds;
            return push(next, {
              kind: "order",
              id: takeId(next),
              order: {
                orderId:
                  (pending?.input?.order_id as string) ??
                  exceeds?.orderId ??
                  "",
                name: exceeds?.name ?? "item",
                amountUsd: exceeds?.amountUsd ?? null,
                deliveryDate: null,
              },
            });
          }
          if (result.stage === "verification") {
            return push(next, {
              kind: "system",
              id: takeId(next),
              text: "Payment blocked by your vault",
            });
          }
          return push(next, {
            kind: "system",
            id: takeId(next),
            text: "Declined on Ledger",
          });
        default:
          return next;
      }
    }
    case "error":
      return push(
        { ...state, busy: false },
        { kind: "error", id: takeId(state), text: event.error as string },
      );
    case "done":
      return { ...state, busy: false };
    default:
      return state;
  }
}
