"use client";

import type { StoryContext } from "@/lib/caption.ts";
import { usd } from "@/lib/money.ts";
import {
  AgentIcon,
  AttackerIcon,
  CheckIcon,
  LedgerIcon,
  LockIcon,
  SatchelIcon,
  VaultIcon,
  XIcon,
} from "@/components/icons";

function Row({
  icon,
  title,
  detail,
  tone,
}: {
  icon: React.ReactNode;
  title: string;
  detail: string;
  tone: "bad" | "good" | "muted";
}) {
  const colors = {
    bad: "bg-bad-soft text-bad",
    good: "bg-good-soft text-good",
    muted: "bg-canvas text-ink-soft",
  };
  return (
    <div className="flex items-center gap-4 rounded-xl border border-line bg-surface px-4 py-3 short:py-2">
      <span className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-full short:h-9 short:w-9 ${colors[tone]}`}>
        {icon}
      </span>
      <div className="min-w-0">
        <div className="text-[17px] font-semibold text-ink">{title}</div>
        <div className="text-[14px] leading-snug text-ink-soft">{detail}</div>
      </div>
    </div>
  );
}

export function AttackPanel({
  ctx,
  mainFundsSats,
}: {
  ctx: StoryContext;
  mainFundsSats: number | null;
}) {
  const { attack } = ctx;
  const satchel = attack.budgetSats;
  const drained = attack.drainedSats !== null;
  return (
    <div data-testid="attack-panel" className="flex items-center gap-6 px-10 py-4">
      <section className="flex min-w-0 flex-1 flex-col gap-3 rounded-2xl border-2 border-bad/30 bg-bad-soft/40 p-5 short:gap-2 short:p-4">
        <div className="flex items-center gap-2 text-[13px] font-semibold tracking-[0.14em] text-bad uppercase">
          <AttackerIcon className="h-5 w-5" /> The attacker controls
        </div>
        <Row
          icon={<AgentIcon className="h-6 w-6" />}
          title="Your agent"
          detail="Its prompts, its tools, its session. Everything."
          tone="bad"
        />
        <Row
          icon={<SatchelIcon className="h-6 w-6" />}
          title={
            drained
              ? `Satchel: ${usd(0)} left`
              : `Satchel: ${satchel !== null ? usd(satchel) : "its budget"}`
          }
          detail={
            drained
              ? `${usd(attack.drainedSats!)} sent to the attacker. The worst case, and it's capped.`
              : "Its key can spend this satchel, and nothing else."
          }
          tone="bad"
        />
      </section>

      <section className="flex min-w-0 flex-1 flex-col gap-3 rounded-2xl border-2 border-good/25 bg-good-soft/40 p-5 short:gap-2 short:p-4">
        <div className="flex items-center gap-2 text-[13px] font-semibold tracking-[0.14em] text-good uppercase">
          <LockIcon className="h-5 w-5" /> Out of reach
        </div>
        <Row
          icon={<LockIcon className="h-6 w-6" />}
          title={`Main funds${mainFundsSats !== null ? `: ${usd(mainFundsSats)}` : ""}`}
          detail="Moving them needs a signature from your Ledger."
          tone="good"
        />
        <Row
          icon={<VaultIcon className="h-6 w-6" />}
          title="The seed"
          detail="Offline in the vault. Satchel keys are hardened, so they can't lead back to it."
          tone="good"
        />
        {attack.requestSats !== null && (
          <div
            data-testid="attack-request"
            data-outcome={attack.outcome ?? "pending"}
            className={`animate-rise flex items-center gap-4 rounded-xl border px-4 py-3 short:py-2 ${
              attack.outcome === "rejected"
                ? "border-good/40 bg-surface"
                : attack.outcome === "approved"
                  ? "border-bad/50 bg-surface"
                  : "border-line bg-surface"
            }`}
          >
            <span
              className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-full short:h-9 short:w-9 ${
                attack.outcome === "rejected"
                  ? "bg-good text-white"
                  : attack.outcome === "approved"
                    ? "bg-bad text-white"
                    : "bg-canvas text-ink-soft"
              }`}
            >
              {attack.outcome === "rejected" ? (
                <XIcon className="h-6 w-6" />
              ) : attack.outcome === "approved" ? (
                <CheckIcon className="h-6 w-6" />
              ) : (
                <LedgerIcon className="h-6 w-6" />
              )}
            </span>
            <div className="min-w-0">
              <div className="text-[17px] font-semibold text-ink">
                Attacker asks for {usd(attack.requestSats)}
              </div>
              <div className="text-[14px] text-ink-soft">
                {attack.outcome === "rejected"
                  ? "Rejected on your Ledger. Nothing moved."
                  : attack.outcome === "approved"
                    ? "Approved on the Ledger: main funds moved."
                    : "Waiting for your Ledger."}
              </div>
            </div>
          </div>
        )}
      </section>
    </div>
  );
}
