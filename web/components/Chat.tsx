"use client";

import {
  useCallback,
  useEffect,
  useReducer,
  useRef,
  useState,
  type RefObject,
} from "react";
import {
  approvalText,
  initialChatState,
  reduce,
  sendUserMessage,
  type Approval,
  type Block,
  type ChatEvent,
  type ChatState,
  type OrderInfo,
  type Product,
} from "@/lib/chat.ts";
import type { BudgetView } from "@/lib/balances.ts";
import { maskSecrets } from "@/lib/mask.ts";
import { btc, usd, usdFromDollars } from "@/lib/money.ts";
import { getOrder, streamChat } from "@/lib/api.ts";
import { LightMarkdown } from "@/components/markdown";
import {
  CategoryIcon,
  CheckIcon,
  LedgerIcon,
  ShieldIcon,
} from "@/components/icons";

export interface ChatControls {
  send: (text: string) => void;
  newChat: () => void;
}

type ChatAction =
  | ChatEvent
  | { type: "__send"; text: string }
  | { type: "__reset" };

function chatReducer(state: ChatState, action: ChatAction): ChatState {
  if (action.type === "__send") {
    return sendUserMessage(state, action.text as string);
  }
  if (action.type === "__reset") {
    return { ...initialChatState, nextId: state.nextId };
  }
  return reduce(state, action);
}

const SUGGESTED_PROMPTS = [
  "Find me headphones under $200 that arrive by Friday",
  "Get me a $200 budget for today",
  "Buy me the Featherbook 13 laptop",
];

const MONTHS = [
  "Jan", "Feb", "Mar", "Apr", "May", "Jun",
  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
];
const DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

export function arrivalText(deliveryDate: string | null): string | null {
  if (!deliveryDate) return null;
  const d = new Date(`${deliveryDate}T00:00:00Z`);
  if (Number.isNaN(d.getTime())) return null;
  return `Arrives ${DAYS[d.getUTCDay()]} ${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]}`;
}

export function BudgetPill({ budget }: { budget: BudgetView | null }) {
  if (!budget) {
    return (
      <div
        data-testid="budget-pill"
        className="rounded-full border border-line bg-surface px-4 py-2 text-[15px] text-muted"
      >
        No budget yet
      </div>
    );
  }
  const pct =
    budget.budgetSats > 0
      ? Math.max(0, Math.min(100, (budget.remainingSats / budget.budgetSats) * 100))
      : 0;
  return (
    <div
      data-testid="budget-pill"
      className="flex flex-col gap-1.5 rounded-full border border-line bg-surface px-4 pt-2 pb-2.5 @[560px]:min-w-[178px]"
    >
      <span className="text-[15px] leading-none whitespace-nowrap text-ink-soft">
        <span className="hidden @[560px]:inline">Budget </span>
        <span className="font-semibold text-ink tabular-nums">
          {usd(budget.remainingSats)}
        </span>{" "}
        of {usd(budget.budgetSats)}
      </span>
      <span className="block h-[3px] overflow-hidden rounded-full bg-line">
        <span
          className="block h-full rounded-full bg-accent transition-[width] duration-700"
          style={{ width: `${pct}%` }}
        />
      </span>
    </div>
  );
}

function XrayToggle({ on, onToggle }: { on: boolean; onToggle: () => void }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      onClick={onToggle}
      className="flex shrink-0 items-center gap-2.5 rounded-full border border-line bg-surface py-2 pr-2 pl-4 text-[15px] font-medium whitespace-nowrap text-ink-soft transition hover:text-ink"
    >
      X-ray
      <span
        className={`relative h-6 w-10 rounded-full transition-colors ${
          on ? "bg-accent" : "bg-line"
        }`}
      >
        <span
          className={`absolute top-0.5 left-0.5 h-5 w-5 rounded-full bg-white shadow-sm transition-transform ${
            on ? "translate-x-4" : ""
          }`}
        />
      </span>
    </button>
  );
}

function ProductCard({
  product,
  onBuy,
  disabled,
}: {
  product: Product;
  onBuy: (name: string) => void;
  disabled: boolean;
}) {
  const arrival = arrivalText(product.delivery_date);
  return (
    <div
      data-testid="product-card"
      className="flex min-w-0 items-center gap-3 rounded-2xl border border-line bg-surface p-3 @[560px]:flex-col @[560px]:items-stretch @[560px]:gap-0 @[560px]:p-4"
    >
      <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-accent-soft text-accent @[560px]:mb-3">
        <CategoryIcon category={product.category} />
      </div>
      <div className="min-w-0 flex-1">
        <div className="line-clamp-2 text-[15px] leading-snug font-semibold text-ink @[560px]:min-h-[2.75em]">
          {product.name}
        </div>
        <div className="flex items-baseline gap-1.5 @[560px]:mt-2">
          <span className="text-[18px] font-semibold text-ink tabular-nums @[560px]:text-[20px]">
            {usdFromDollars(product.price_usd)}
          </span>
          <span className="text-[12px] text-muted">
            {product.price_sats ? btc(product.price_sats) : `${product.price_btc} BTC`}
          </span>
        </div>
        <div className="text-[13px] text-ink-soft @[560px]:mt-0.5 @[560px]:mb-3 @[560px]:text-[14px]">
          {arrival ?? "\u00a0"}
        </div>
      </div>
      <button
        type="button"
        onClick={() => onBuy(product.name)}
        disabled={disabled || !product.available}
        className="shrink-0 rounded-full bg-accent px-4 py-2 text-[15px] font-medium text-white transition hover:bg-accent-ink disabled:opacity-40 @[560px]:mt-auto @[560px]:px-3"
      >
        Buy
      </button>
    </div>
  );
}

function OrderCard({ order }: { order: OrderInfo }) {
  const [status, setStatus] = useState<string>("awaiting_payment");
  useEffect(() => {
    if (!order.orderId) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;
    const poll = async () => {
      try {
        const latest = await getOrder(order.orderId);
        if (cancelled) return;
        if (typeof latest.status === "string") setStatus(latest.status);
        if (latest.status === "paid") return;
      } catch (err) {
        console.debug("order status unavailable", err);
      }
      if (!cancelled) timer = setTimeout(poll, 2500);
    };
    void poll();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [order.orderId]);

  const paid = status === "paid";
  const arrival = arrivalText(order.deliveryDate);
  return (
    <div
      data-testid="order-card"
      className="animate-rise flex items-center gap-4 rounded-2xl border border-line bg-surface px-4 py-3.5"
    >
      <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-accent-soft text-accent">
        <CategoryIcon category={order.category} />
      </div>
      <div className="min-w-0 flex-1">
        <div className="truncate text-[16px] font-semibold text-ink">{order.name}</div>
        <div className="text-[14px] text-ink-soft">
          {[
            order.amountUsd !== null ? usdFromDollars(order.amountUsd) : null,
            arrival,
          ]
            .filter(Boolean)
            .join(" · ")}
        </div>
      </div>
      <span
        data-testid="order-status"
        className={`inline-flex shrink-0 items-center gap-1.5 rounded-full px-3 py-1.5 text-[14px] font-medium ${
          paid ? "bg-good-soft text-good" : "bg-accent-soft text-accent-ink"
        }`}
      >
        {paid ? (
          <CheckIcon className="h-4 w-4" />
        ) : (
          <span className="animate-blink h-2 w-2 rounded-full bg-accent" />
        )}
        {paid ? "Paid" : "Confirming"}
      </span>
    </div>
  );
}

const APPROVAL_STYLES: Record<Approval["status"], string> = {
  pending: "border-accent/30 bg-accent-soft text-accent-ink",
  approved: "border-good/25 bg-good-soft text-good",
  rejected: "border-line bg-surface text-ink-soft",
  blocked: "border-bad/30 bg-bad-soft text-bad",
  failed: "border-line bg-surface text-ink-soft",
};

function ApprovalRow({ approval }: { approval: Approval }) {
  return (
    <div className="flex justify-center">
      <div
        data-testid="approval-row"
        data-status={approval.status}
        className={`animate-rise inline-flex max-w-full items-center gap-2.5 rounded-2xl border px-4 py-2 text-[15px] leading-snug ${APPROVAL_STYLES[approval.status]}`}
      >
        {approval.status === "blocked" ? (
          <ShieldIcon className="h-5 w-5 shrink-0" />
        ) : (
          <LedgerIcon className="h-5 w-5 shrink-0" />
        )}
        <span>{approvalText(approval)}</span>
        {approval.status === "pending" && (
          <span className="animate-blink h-2 w-2 shrink-0 rounded-full bg-accent" />
        )}
        {approval.status === "approved" && <CheckIcon className="h-4 w-4 shrink-0" />}
      </div>
    </div>
  );
}

function Typing() {
  return (
    <div className="flex items-center gap-1.5 py-1" aria-label="Thinking">
      {[0, 1, 2].map((i) => (
        <span
          key={i}
          className="animate-blink h-2 w-2 rounded-full bg-muted"
          style={{ animationDelay: `${i * 0.2}s` }}
        />
      ))}
    </div>
  );
}

function BlockView({
  block,
  onBuy,
  onRetry,
  busy,
}: {
  block: Block;
  onBuy: (name: string) => void;
  onRetry: (message: string) => void;
  busy: boolean;
}) {
  switch (block.kind) {
    case "user":
      return (
        <div className="flex justify-end">
          <div className="max-w-[80%] rounded-3xl bg-ink px-5 py-3 text-[17px] leading-snug text-white">
            {block.text}
          </div>
        </div>
      );
    case "assistant":
      return (
        <div className="max-w-[92%] text-[17px] leading-relaxed text-ink">
          <LightMarkdown text={maskSecrets(block.text)} />
        </div>
      );
    case "cards":
      return (
        <div className="grid grid-cols-1 gap-2.5 @[560px]:grid-cols-3 @[560px]:gap-3">
          {block.products.map((p) => (
            <ProductCard key={p.id} product={p} onBuy={onBuy} disabled={busy} />
          ))}
        </div>
      );
    case "activity":
      return <div className="text-[15px] text-muted">{block.text}</div>;
    case "approval":
      return <ApprovalRow approval={block.approval} />;
    case "order":
      return <OrderCard order={block.order} />;
    case "retry":
      return (
        <div className="flex justify-center">
          <div
            data-testid="retry-row"
            className="inline-flex items-center gap-3 rounded-full border border-line bg-surface py-1.5 pr-1.5 pl-4 text-[15px] text-ink-soft"
          >
            That didn&apos;t go through.
            {block.message && (
              <button
                type="button"
                onClick={() => onRetry(block.message!)}
                disabled={busy}
                className="rounded-full bg-ink px-3.5 py-1.5 text-[14px] font-medium text-white transition hover:bg-ink-soft disabled:opacity-40"
              >
                Try again
              </button>
            )}
          </div>
        </div>
      );
  }
}

export default function Chat({
  budget,
  xrayOpen,
  onToggleXray,
  onSession,
  onBusy,
  controlsRef,
}: {
  budget: BudgetView | null;
  xrayOpen: boolean;
  onToggleXray: () => void;
  onSession?: (sessionId: string | null) => void;
  onBusy?: (busy: boolean) => void;
  controlsRef?: RefObject<ChatControls | null>;
}) {
  const [state, dispatch] = useReducer(chatReducer, initialChatState);
  const [input, setInput] = useState("");
  const abortRef = useRef<AbortController | null>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const sessionRef = useRef<string | null>(null);
  const queuedRef = useRef<string[]>([]);

  useEffect(() => {
    sessionRef.current = state.sessionId;
    onSession?.(state.sessionId);
  }, [state.sessionId, onSession]);

  useEffect(() => {
    if (state.lastError) console.warn("[satchel] chat:", state.lastError);
  }, [state.lastError]);

  useEffect(() => {
    onBusy?.(state.busy);
  }, [state.busy, onBusy]);

  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
  }, [state.blocks, state.busy]);

  useEffect(() => () => abortRef.current?.abort(), []);

  const send = useCallback(
    (raw: string) => {
      const text = raw.trim();
      if (!text) return;
      if (state.busy) {
        queuedRef.current.push(text);
        return;
      }
      setInput("");
      dispatch({ type: "__send", text });
      const controller = new AbortController();
      abortRef.current = controller;
      void (async () => {
        try {
          for await (const event of streamChat(
            text,
            sessionRef.current,
            controller.signal,
          )) {
            dispatch(event as ChatEvent);
          }
        } catch (err) {
          if (!controller.signal.aborted) {
            dispatch({
              type: "error",
              error: err instanceof Error ? err.message : "request failed",
            });
          }
        } finally {
          if (abortRef.current === controller) abortRef.current = null;
        }
      })();
    },
    [state.busy],
  );

  useEffect(() => {
    if (state.busy) return;
    const next = queuedRef.current.shift();
    if (next !== undefined) send(next);
  }, [state.busy, send]);

  const newChat = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    queuedRef.current = [];
    sessionRef.current = null;
    dispatch({ type: "__reset" });
    setInput("");
  }, []);

  useEffect(() => {
    if (controlsRef) controlsRef.current = { send, newChat };
  }, [send, newChat, controlsRef]);

  const empty = state.blocks.length === 0;
  const last = state.blocks[state.blocks.length - 1];
  const showTyping =
    state.busy &&
    last?.kind !== "activity" &&
    !(last?.kind === "approval" && last.approval.status === "pending") &&
    last?.kind !== "assistant";

  return (
    <div className="@container flex h-full w-full flex-col items-center">
      <header className="flex w-full max-w-[720px] items-center justify-between gap-3 px-5 pt-5 pb-3 @[560px]:gap-4 @[560px]:px-6 @[560px]:pt-6 @[560px]:pb-4">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-ink text-[18px] font-semibold text-white">
            S
          </div>
          {/* In a narrow phone frame the logo alone carries the name. */}
          <div className="sr-only @[440px]:not-sr-only">
            <h1 className="text-[22px] leading-tight font-semibold text-ink">Satchel</h1>
            <p className="hidden text-[14px] text-muted @[560px]:block">Your personal shopper</p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <BudgetPill budget={budget} />
          <XrayToggle on={xrayOpen} onToggle={onToggleXray} />
        </div>
      </header>

      <div ref={scrollRef} className="w-full flex-1 overflow-y-auto">
        <div className="mx-auto flex min-h-full w-full max-w-[720px] flex-col gap-5 px-6 py-6">
          {empty && (
            <div className="flex flex-1 flex-col items-center justify-center gap-7">
              <div className="text-center">
                <div className="text-[30px] font-semibold text-ink">
                  What can I get you today?
                </div>
                <p className="mt-2 text-[16px] text-ink-soft">
                  I shop within a budget you approve, and ask before anything big.
                </p>
              </div>
              <div className="flex w-full max-w-md flex-col gap-2.5">
                {SUGGESTED_PROMPTS.map((prompt) => (
                  <button
                    key={prompt}
                    type="button"
                    onClick={() => send(prompt)}
                    className="rounded-2xl border border-line bg-surface px-5 py-3.5 text-left text-[16px] text-ink-soft transition hover:border-accent/40 hover:text-ink"
                  >
                    {prompt}
                  </button>
                ))}
              </div>
            </div>
          )}
          {state.blocks.map((block) => (
            <BlockView
              key={block.id}
              block={block}
              onBuy={(name) => send(`Buy the ${name}.`)}
              onRetry={send}
              busy={state.busy}
            />
          ))}
          {showTyping && <Typing />}
        </div>
      </div>

      <div className="w-full max-w-[720px] px-6 pt-2 pb-6">
        <form
          className="flex gap-2.5"
          onSubmit={(e) => {
            e.preventDefault();
            send(input);
          }}
        >
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Ask for anything…"
            className="flex-1 rounded-full border border-line bg-surface px-5 py-3.5 text-[17px] outline-none placeholder:text-muted focus:border-accent/50"
            aria-label="Message"
          />
          <button
            type="submit"
            disabled={state.busy || !input.trim()}
            className="rounded-full bg-accent px-6 py-3.5 text-[17px] font-medium text-white transition hover:bg-accent-ink disabled:opacity-40"
          >
            Send
          </button>
        </form>
      </div>
    </div>
  );
}
