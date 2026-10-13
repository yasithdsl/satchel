"use client";

import type { BudgetView } from "@/lib/balances.ts";
import { usd } from "@/lib/money.ts";

function Figure({
  label,
  value,
  sub,
  tone = "ink",
  testId,
}: {
  label: string;
  value: string;
  sub: string | null;
  tone?: "ink" | "bad" | "muted";
  testId: string;
}) {
  const color =
    tone === "bad" ? "text-bad" : tone === "muted" ? "text-muted" : "text-ink";
  return (
    <div
      data-testid={testId}
      className={`animate-rise min-w-0 rounded-2xl border px-5 py-4 short:py-2.5 ${
        tone === "bad" ? "border-bad/25 bg-bad-soft" : "border-line bg-surface"
      }`}
    >
      <div
        className={`text-[14px] font-medium ${tone === "bad" ? "text-bad" : "text-ink-soft"}`}
      >
        {label}
      </div>
      <div
        data-testid={`${testId}-value`}
        className={`mt-1 font-semibold whitespace-nowrap tabular-nums ${color} ${
          tone === "muted"
            ? "text-[clamp(22px,1.5vw,28px)] leading-[1.5] short:text-[clamp(20px,1.3vw,24px)]"
            : "text-[clamp(30px,2.2vw,42px)] leading-tight short:text-[clamp(26px,1.9vw,34px)]"
        }`}
      >
        {value}
        {sub && (
          <span
            className={`ml-2 text-[clamp(14px,0.85vw,16px)] font-normal ${
              tone === "bad" ? "text-bad/80" : "text-muted"
            }`}
          >
            {sub}
          </span>
        )}
      </div>
    </div>
  );
}

export function NumbersRow({
  mainFundsSats,
  budget,
  lostSats,
  showLost,
}: {
  mainFundsSats: number | null;
  budget: BudgetView | null;
  lostSats: number;
  showLost: boolean;
}) {
  return (
    <section
      data-testid="numbers-row"
      className="grid shrink-0 grid-cols-3 gap-4 border-t border-line px-10 py-5 short:py-3"
    >
      <Figure
        testId="number-main-funds"
        label="Main funds"
        value={mainFundsSats !== null ? usd(mainFundsSats) : "…"}
        sub={null}
      />
      {budget ? (
        <Figure
          testId="number-agent-budget"
          label="Agent's satchel"
          value={usd(budget.remainingSats)}
          sub={`of ${usd(budget.budgetSats)}`}
        />
      ) : (
        <Figure
          testId="number-agent-budget"
          label="Agent's satchel"
          value="None yet"
          sub={null}
          tone="muted"
        />
      )}
      {showLost ? (
        <Figure
          testId="number-lost"
          label="Lost to attacker"
          value={usd(lostSats)}
          sub="simulated"
          tone="bad"
        />
      ) : (
        <div aria-hidden="true" />
      )}
    </section>
  );
}
