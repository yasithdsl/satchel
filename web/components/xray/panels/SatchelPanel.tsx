"use client";

import type { SatchelMilestone, StoryContext } from "@/lib/caption.ts";
import { usd } from "@/lib/money.ts";
import {
  AgentIcon,
  ArrowIcon,
  CheckIcon,
  KeyIcon,
  LockIcon,
  SatchelIcon,
} from "@/components/icons";

const CHECKLIST: { id: SatchelMilestone; text: string }[] = [
  { id: "asked", text: "Agent asks for a budget" },
  { id: "key", text: "Vault derives a fresh, hardened key" },
  { id: "drafted", text: "Laptop drafts the funding; it stores no keys" },
  { id: "approved", text: "You approve once, on your Ledger" },
  { id: "keys", text: "Vault releases one-time keys, never the seed" },
  { id: "signed", text: "Offline signer signs the funding" },
  { id: "verified", text: "Vault checks every signature byte" },
  { id: "confirmed", text: "Funding confirmed in a block" },
  { id: "handed", text: "Agent gets the satchel key" },
];

function PathView({ path }: { path: string | null }) {
  const parts = (path ?? "m/84'/1'/0'/2'/i'").split("/");
  return (
    <div className="mt-5 rounded-2xl border border-line bg-surface px-5 py-4 short:mt-3 short:py-3">
      <div className="text-[13px] font-semibold tracking-[0.14em] text-muted uppercase">
        Satchel key
      </div>
      <div
        data-testid="satchel-path"
        className="mt-2 font-mono text-[clamp(20px,1.5vw,28px)] font-semibold text-ink"
      >
        {parts.map((part, i) => (
          <span key={i}>
            {i > 0 && <span className="px-1 text-muted">/</span>}
            {part.replace("'", "")}
            {part.endsWith("'") && <span className="text-accent">&apos;</span>}
          </span>
        ))}
      </div>
      <p className="mt-2 text-[15px] leading-snug text-ink-soft">
        <span className="font-semibold text-accent">&apos;</span> means hardened, at every
        level. A leaked satchel key reveals nothing about your other keys.
      </p>
    </div>
  );
}

function Box({
  icon,
  title,
  value,
  sub,
  lit,
  tone = "accent",
}: {
  icon: React.ReactNode;
  title: string;
  value: string | null;
  sub: string;
  lit: boolean;
  tone?: "accent" | "good";
}) {
  return (
    <div
      className={`flex min-w-0 flex-1 flex-col items-center rounded-2xl border bg-surface px-3 py-4 text-center transition-all duration-500 short:py-3 ${
        lit
          ? tone === "good"
            ? "border-good/40 shadow-[0_0_0_3px_rgb(23_128_61/0.12)]"
            : "border-accent/40 shadow-[0_0_0_3px_rgb(52_81_209/0.12)]"
          : "border-line"
      }`}
    >
      <span
        className={`flex h-12 w-12 items-center justify-center rounded-full short:h-10 short:w-10 ${
          lit ? (tone === "good" ? "bg-good text-white" : "bg-accent text-white") : "bg-accent-soft text-accent"
        }`}
      >
        {icon}
      </span>
      <div className="mt-2 text-[15px] font-semibold text-ink">{title}</div>
      {value && (
        <div className="text-[clamp(20px,1.5vw,26px)] font-semibold text-ink tabular-nums">{value}</div>
      )}
      <div className="text-[13px] leading-snug text-muted">{sub}</div>
    </div>
  );
}

function Arrow({ label, lit }: { label: string; lit: boolean }) {
  return (
    <div className="flex shrink-0 flex-col items-center px-1">
      <span className={`text-[13px] font-semibold ${lit ? "text-accent" : "text-muted"}`}>{label}</span>
      <ArrowIcon className={`h-7 w-10 ${lit ? "text-accent" : "text-line"}`} />
    </div>
  );
}

export function SatchelPanel({
  ctx,
  mainFundsSats,
}: {
  ctx: StoryContext;
  mainFundsSats: number | null;
}) {
  const done = new Set(ctx.satchel.milestones);
  const budget = ctx.satchel.budgetSats;
  const nextIndex = CHECKLIST.findIndex((c) => !done.has(c.id));
  return (
    <div data-testid="satchel-panel" className="flex items-center gap-8 px-10 py-4">
      <div className="flex min-w-0 flex-[1.1] flex-col justify-center">
        <div className="flex items-stretch gap-1">
          <Box
            icon={<LockIcon className="h-6 w-6" />}
            title="Main funds"
            value={mainFundsSats !== null ? usd(mainFundsSats) : null}
            sub="keys stay in the offline vault"
            lit={done.has("confirmed") && !done.has("handed")}
          />
          <Arrow label={budget !== null ? usd(budget) : "funds"} lit={done.has("confirmed")} />
          <Box
            icon={<SatchelIcon className="h-6 w-6" />}
            title="New satchel"
            value={budget !== null ? usd(budget) : null}
            sub={done.has("confirmed") ? "funded and confirmed" : "waiting for your Ledger"}
            lit={done.has("confirmed")}
            tone="good"
          />
          <Arrow label="key" lit={done.has("handed")} />
          <Box
            icon={<AgentIcon className="h-6 w-6" />}
            title="Agent"
            value={null}
            sub={done.has("handed") ? "holds one key, nothing else" : "holds nothing yet"}
            lit={done.has("handed")}
            tone="good"
          />
        </div>
        <PathView path={ctx.satchel.path} />
      </div>
      <ol data-testid="satchel-checklist" className="flex min-w-0 flex-1 flex-col justify-center gap-1.5 short:gap-0.5">
        {CHECKLIST.map((item, i) => {
          const isDone = done.has(item.id);
          const isNext = i === nextIndex;
          return (
            <li
              key={item.id}
              data-done={isDone || undefined}
              className={`flex items-center gap-3 rounded-xl px-3 py-1.5 text-[clamp(14px,1vw,17px)] transition-colors short:py-1 ${
                isNext ? "bg-accent-soft text-ink" : isDone ? "text-ink" : "text-muted"
              }`}
            >
              <span
                className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full border text-[12px] short:h-5 short:w-5 ${
                  isDone ? "border-good bg-good text-white" : isNext ? "border-accent text-accent" : "border-line"
                }`}
              >
                {isDone ? <CheckIcon className="h-4 w-4" /> : i + 1}
              </span>
              {item.text}
              {item.id === "approved" && (
                <span className="ml-auto shrink-0 rounded-full bg-canvas px-2 py-0.5 text-[12px] text-ink-soft">
                  your only tap
                </span>
              )}
              {item.id === "keys" && isDone && (
                <KeyIcon className="ml-auto h-4 w-4 shrink-0 text-muted" />
              )}
            </li>
          );
        })}
      </ol>
    </div>
  );
}
