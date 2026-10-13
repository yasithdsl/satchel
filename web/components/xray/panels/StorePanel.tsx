"use client";

import type { StoryContext } from "@/lib/caption.ts";
import { usd, usdFromDollars } from "@/lib/money.ts";
import { arrivalText } from "@/components/Chat";
import { CategoryIcon, CheckIcon, LedgerIcon, SatchelIcon, SearchIcon } from "@/components/icons";

const MAX_TILES = 6;

export function StorePanel({ ctx }: { ctx: StoryContext }) {
  const { store } = ctx;
  const budget = ctx.satchel.budgetSats;
  const ranked = new Map(store.suggested.map((id, i) => [id, i + 1]));
  const tiles = [...store.results]
    .sort((a, b) => (ranked.get(a.id) ?? 99) - (ranked.get(b.id) ?? 99))
    .slice(0, MAX_TILES);
  const chosen = store.results.find((r) => r.id === store.chosen) ?? null;
  const overBudget =
    chosen?.priceSats != null && budget !== null && chosen.priceSats > budget;

  return (
    <div data-testid="store-panel" className="flex items-center gap-6 px-10 py-4">
      <div className="@container/store flex min-w-0 flex-[2] flex-col overflow-hidden rounded-2xl border border-line bg-surface">
        <div className="flex items-center gap-4 border-b border-line bg-[#f3f1ec] px-5 py-3">
          <span className="shrink-0 text-[17px] font-semibold tracking-tight text-ink">
            satchel<span className="text-accent">.market</span>
          </span>
          <div className="flex min-w-0 flex-1 items-center gap-2 rounded-full border border-line bg-surface px-4 py-1.5 text-[15px] text-ink">
            <SearchIcon className="h-4 w-4 shrink-0 text-muted" />
            <span data-testid="store-query" className="truncate">
              {store.query ?? "…"}
            </span>
          </div>
          {store.maxUsd !== null && (
            <span className="shrink-0 rounded-full bg-accent-soft px-3 py-1 text-[13px] text-accent-ink">
              under {usdFromDollars(store.maxUsd)}
            </span>
          )}
          {/* The search matters more than this label when the store is narrow. */}
          <span className="hidden shrink-0 text-[13px] text-muted @min-[38rem]/store:inline">demo store</span>
        </div>
        {tiles.length > 0 ? (
          <div className="grid flex-1 grid-cols-3 content-start gap-3 p-4">
            {tiles.map((item) => {
              const rank = ranked.get(item.id);
              const isChosen = item.id === store.chosen;
              const dim = store.chosen !== null ? !isChosen : store.suggested.length > 0 && !rank;
              return (
                <div
                  key={item.id}
                  data-testid="store-tile"
                  data-chosen={isChosen || undefined}
                  className={`relative flex min-w-0 flex-col rounded-xl border p-3 transition-all duration-500 short:flex-row short:items-start short:gap-3 short:pt-4 ${
                    isChosen
                      ? "border-accent shadow-[0_0_0_3px_rgb(52_81_209/0.15)]"
                      : rank
                        ? "border-accent/30"
                        : "border-line"
                  } ${dim ? "opacity-35" : ""}`}
                >
                  {(rank || isChosen) && (
                    <span
                      className={`absolute -top-2.5 left-3 rounded-full px-2 py-0.5 text-[11px] font-semibold ${
                        isChosen ? "bg-accent text-white" : "bg-accent-soft text-accent-ink"
                      }`}
                    >
                      {isChosen ? "Agent's choice" : rank === 1 ? "Best match" : `Pick ${rank}`}
                    </span>
                  )}
                  {/* On short screens the picture sits beside the details. */}
                  <div className="flex h-14 items-center justify-center rounded-lg bg-canvas text-ink-soft short:h-10 short:w-10 short:shrink-0">
                    <CategoryIcon category={item.category} className="h-7 w-7 short:h-6 short:w-6" />
                  </div>
                  <div className="flex min-w-0 flex-1 flex-col">
                    <div className="mt-2 line-clamp-2 text-[14px] leading-snug font-semibold text-ink short:mt-0 short:line-clamp-3">
                      {item.name}
                    </div>
                    <div className="mt-auto pt-1 text-[16px] font-semibold text-ink tabular-nums">
                      {item.priceSats !== null ? usd(item.priceSats) : ""}
                    </div>
                    <div className="text-[12px] text-muted">{arrivalText(item.deliveryDate) ?? ""}</div>
                  </div>
                </div>
              );
            })}
          </div>
        ) : (
          <div className="flex flex-1 items-center justify-center text-[16px] text-muted">
            Your agent is looking…
          </div>
        )}
      </div>

      <div className="flex min-w-0 flex-1 flex-col justify-center">
        <div data-testid="store-checkout" className="rounded-2xl border border-line bg-surface p-5 short:p-4">
          <div className="text-[13px] font-semibold tracking-[0.14em] text-muted uppercase">Checkout</div>
          {chosen ? (
            <>
              <div className="mt-2 text-[18px] leading-snug font-semibold text-ink">{chosen.name}</div>
              <div className="text-[26px] font-semibold text-ink tabular-nums">
                {chosen.priceSats !== null ? usd(chosen.priceSats) : ""}
              </div>
              <div className="mt-4 flex items-center gap-3 rounded-xl bg-canvas px-3 py-2.5">
                {overBudget ? (
                  <LedgerIcon className="h-6 w-6 shrink-0 text-ink-soft" />
                ) : (
                  <SatchelIcon className="h-6 w-6 shrink-0 text-good" />
                )}
                <div className="text-[15px] leading-snug text-ink">
                  {overBudget ? (
                    <>
                      Over the {budget !== null ? usd(budget) : ""} satchel.
                      <br />
                      <span className="text-ink-soft">Needs main funds and your Ledger.</span>
                    </>
                  ) : (
                    <>
                      Pay from the agent&apos;s satchel
                      {budget !== null ? ` (${usd(budget)})` : ""}.
                      <br />
                      <span className="text-ink-soft">Within the limit: no Ledger tap.</span>
                    </>
                  )}
                </div>
              </div>
              {store.paidSats !== null && (
                <div
                  data-testid="store-paid"
                  className="animate-rise mt-3 flex items-center gap-2 rounded-xl bg-good-soft px-3 py-2.5 text-[15px] font-medium text-good"
                >
                  <CheckIcon className="h-5 w-5 shrink-0" />
                  {store.confirmed ? "Paid and confirmed" : `Paid ${usd(store.paidSats)} from the satchel`}
                  {store.changeSats !== null && (
                    <span className="ml-auto font-normal">{usd(store.changeSats)} left</span>
                  )}
                </div>
              )}
            </>
          ) : (
            <p className="mt-2 text-[16px] leading-snug text-ink-soft">
              The agent compares the options. It can only pay from its satchel, so it can never
              overspend.
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
