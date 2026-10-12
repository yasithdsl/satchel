"use client";

import {
  useCallback,
  useEffect,
  useReducer,
  useRef,
  useState,
} from "react";
import {
  initialChatState,
  reduce,
  sendUserMessage,
  type Block,
  type ChatEvent,
  type ChatState,
  type Product,
} from "@/lib/chat.ts";
import { maskSecrets } from "@/lib/mask.ts";
import { getOrder, streamChat } from "@/lib/api.ts";
import { LightMarkdown } from "@/components/markdown";

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

const CATEGORY_GRADIENTS: Record<string, string> = {
  audio: "from-indigo-200 via-sky-100 to-teal-100",
  headphones: "from-indigo-200 via-sky-100 to-teal-100",
  earbuds: "from-violet-200 via-fuchsia-100 to-rose-100",
  laptop: "from-slate-300 via-slate-100 to-violet-100",
  laptops: "from-slate-300 via-slate-100 to-violet-100",
  wearable: "from-emerald-200 via-teal-100 to-sky-100",
  home: "from-amber-200 via-orange-100 to-rose-100",
  kitchen: "from-orange-200 via-amber-100 to-yellow-100",
  camera: "from-cyan-200 via-sky-100 to-indigo-100",
  fitness: "from-lime-200 via-emerald-100 to-teal-100",
  gaming: "from-fuchsia-200 via-violet-100 to-indigo-100",
};

function categoryGradient(category: string): string {
  return (
    CATEGORY_GRADIENTS[category?.toLowerCase() ?? ""] ??
    "from-stone-200 via-neutral-100 to-amber-100"
  );
}

const MONTHS = [
  "Jan", "Feb", "Mar", "Apr", "May", "Jun",
  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
];
const DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

export function arrivalText(deliveryDate: string | null): string | null {
  if (!deliveryDate) return null;
  const d = new Date(`${deliveryDate}T00:00:00Z`);
  if (Number.isNaN(d.getTime())) return deliveryDate;
  return `Arrives ${DAYS[d.getUTCDay()]} ${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]}`;
}

function LockIcon() {
  return (
    <svg
      viewBox="0 0 16 16"
      className="h-3 w-3"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      aria-hidden="true"
    >
      <rect x="3" y="7" width="10" height="7" rx="1.5" />
      <path d="M5.5 7V5a2.5 2.5 0 0 1 5 0v2" />
    </svg>
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
  return (
    <div className="w-44 shrink-0 overflow-hidden rounded-2xl border border-neutral-200 bg-white shadow-sm">
      <div
        className={`flex h-20 items-center justify-center bg-gradient-to-br ${categoryGradient(product.category)}`}
      >
        <span className="rounded-full bg-white/70 px-2 py-0.5 text-[10px] font-medium tracking-wide text-neutral-600 uppercase">
          {product.category}
        </span>
      </div>
      <div className="space-y-1 p-3">
        <div className="text-xs font-semibold text-neutral-900">
          {product.name}
        </div>
        <div className="text-sm font-semibold text-neutral-900">
          ${Math.round(product.price_usd)}
          <span className="ml-1 text-[10px] font-normal text-neutral-400">
            {product.price_btc} BTC
          </span>
        </div>
        {arrivalText(product.delivery_date) && (
          <div className="text-[11px] text-neutral-500">
            {arrivalText(product.delivery_date)}
          </div>
        )}
        <div className="text-[11px] text-neutral-400">
          Sold by {product.seller}
        </div>
        <button
          type="button"
          onClick={() => onBuy(product.name)}
          disabled={disabled || !product.available}
          className="mt-1 w-full rounded-full bg-neutral-900 px-3 py-1.5 text-xs font-medium text-white transition hover:bg-neutral-700 disabled:opacity-40"
        >
          Buy
        </button>
      </div>
    </div>
  );
}

function OrderChip({ orderId, name, amountUsd, deliveryDate }: {
  orderId: string;
  name: string;
  amountUsd: number | null;
  deliveryDate: string | null;
}) {
  const [status, setStatus] = useState<string>("awaiting_payment");
  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;
    const poll = async () => {
      try {
        const order = await getOrder(orderId);
        if (cancelled) return;
        if (order.status) setStatus(order.status as string);
        if (order.status !== "paid") {
          timer = setTimeout(poll, 3000);
        }
      } catch {
        if (!cancelled) timer = setTimeout(poll, 3000);
      }
    };
    void poll();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [orderId]);

  const paid = status === "paid";
  return (
    <div className="flex items-center gap-3 rounded-2xl border border-neutral-200 bg-white px-4 py-3 shadow-sm">
      <div className="min-w-0 flex-1">
        <div className="truncate text-sm font-semibold text-neutral-900">
          {name}
        </div>
        <div className="text-xs text-neutral-500">
          {amountUsd != null && <>${Math.round(amountUsd)} · </>}
          {arrivalText(deliveryDate) ?? "Order placed"}
        </div>
      </div>
      <span
        className={`shrink-0 rounded-full px-2.5 py-1 text-xs font-medium ${
          paid
            ? "bg-emerald-100 text-emerald-700"
            : "bg-amber-100 text-amber-700"
        }`}
      >
        {paid ? "Paid" : "Payment pending"}
      </span>
    </div>
  );
}

function BlockView({
  block,
  onBuy,
  busy,
}: {
  block: Block;
  onBuy: (name: string) => void;
  busy: boolean;
}) {
  switch (block.kind) {
    case "user":
      return (
        <div className="flex justify-end">
          <div className="max-w-[80%] rounded-2xl bg-neutral-900 px-4 py-2.5 text-sm text-white">
            {block.text}
          </div>
        </div>
      );
    case "assistant":
      return (
        <div className="max-w-[90%] text-sm leading-relaxed text-neutral-800">
          <LightMarkdown text={maskSecrets(block.text)} />
        </div>
      );
    case "cards":
      return (
        <div className="flex gap-3 overflow-x-auto pb-1">
          {block.products.map((p) => (
            <ProductCard
              key={p.id}
              product={p}
              onBuy={onBuy}
              disabled={busy}
            />
          ))}
        </div>
      );
    case "notice":
      return (
        <div className="flex justify-center">
          <div className="inline-flex items-center gap-1.5 rounded-full border border-amber-200 bg-amber-50 px-3 py-1 text-xs text-amber-800">
            <LockIcon />
            {block.text}
          </div>
        </div>
      );
    case "ledger_wait":
      return (
        <div className="flex justify-center">
          <div className="inline-flex items-center gap-2 text-xs text-neutral-500">
            <span className="relative flex h-2 w-2">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-amber-400 opacity-60" />
              <span className="relative inline-flex h-2 w-2 rounded-full bg-amber-500" />
            </span>
            Waiting for your approval on Ledger
          </div>
        </div>
      );
    case "activity":
      return (
        <div className="text-xs text-neutral-400">{block.text}</div>
      );
    case "system":
      return (
        <div className="flex justify-center">
          <div className="rounded-full bg-neutral-100 px-3 py-1 text-xs text-neutral-600">
            {block.text}
          </div>
        </div>
      );
    case "order":
      return <OrderChip {...block.order} />;
    case "error":
      return (
        <div className="flex justify-center">
          <div className="rounded-full bg-red-50 px-3 py-1 text-xs text-red-600">
            {block.text}
          </div>
        </div>
      );
  }
}

export default function Chat({
  onSession,
}: {
  onSession?: (sessionId: string | null) => void;
}) {
  const [state, dispatch] = useReducer(chatReducer, initialChatState);
  const [input, setInput] = useState("");
  const abortRef = useRef<AbortController | null>(null);
  const bottomRef = useRef<HTMLDivElement | null>(null);
  const sessionRef = useRef<string | null>(null);

  useEffect(() => {
    sessionRef.current = state.sessionId;
    onSession?.(state.sessionId);
  }, [state.sessionId, onSession]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [state.blocks]);

  useEffect(() => () => abortRef.current?.abort(), []);

  const send = useCallback(
    (raw: string) => {
      const text = raw.trim();
      if (!text || state.busy) return;
      setInput("");
      dispatch({ type: "__send", text });
      abortRef.current?.abort();
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
        }
      })();
    },
    [state.busy],
  );

  const newChat = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    dispatch({ type: "__reset" });
    setInput("");
  }, []);

  const empty = state.blocks.length === 0;

  return (
    <div className="flex h-full w-full max-w-2xl flex-col">
      <header className="flex items-center justify-between border-b border-neutral-200/60 px-6 pt-5 pb-3">
        <div>
          <h1 className="text-lg font-semibold text-neutral-900">
            Satchel — your personal shopper
          </h1>
          <p className="text-xs text-neutral-400">
            Tell me what you need, I&apos;ll handle the rest
          </p>
        </div>
        {!empty && (
          <button
            type="button"
            onClick={newChat}
            className="rounded-full border border-neutral-200 px-3 py-1 text-xs text-neutral-500 transition hover:text-neutral-800"
          >
            New chat
          </button>
        )}
      </header>

      <div className="flex-1 space-y-4 overflow-y-auto px-6 py-6">
        {empty && (
          <div className="flex h-full flex-col items-center justify-center gap-6">
            <div className="text-center">
              <div className="text-2xl font-semibold text-neutral-900">
                What can I get you today?
              </div>
              <p className="mt-2 text-sm text-neutral-500">
                I can shop a curated store, stay inside a prepaid budget you
                approve, and ask before anything big.
              </p>
            </div>
            <div className="flex w-full max-w-md flex-col gap-2">
              {SUGGESTED_PROMPTS.map((prompt) => (
                <button
                  key={prompt}
                  type="button"
                  onClick={() => send(prompt)}
                  className="rounded-2xl border border-neutral-200 bg-white px-4 py-3 text-left text-sm text-neutral-700 shadow-sm transition hover:border-neutral-300 hover:shadow"
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
            busy={state.busy}
          />
        ))}
        <div ref={bottomRef} />
      </div>

      <div className="border-t border-neutral-200/60 px-6 py-4">
        <form
          className="flex gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            send(input);
          }}
        >
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Ask for anything…"
            className="flex-1 rounded-full border border-neutral-200 bg-white px-4 py-2.5 text-sm shadow-sm outline-none placeholder:text-neutral-400 focus:border-neutral-400"
            aria-label="Message"
          />
          <button
            type="submit"
            disabled={state.busy || !input.trim()}
            className="rounded-full bg-neutral-900 px-5 py-2.5 text-sm font-medium text-white transition hover:bg-neutral-700 disabled:opacity-40"
          >
            Send
          </button>
        </form>
      </div>
    </div>
  );
}
