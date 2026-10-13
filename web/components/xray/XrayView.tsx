"use client";

import { useEffect, useMemo, useState } from "react";
import type { XrayState } from "@/lib/api.ts";
import type { StoryNumbers } from "@/lib/balances.ts";
import type { Chapter, StripNode, Visual } from "@/lib/caption.ts";
import { IDLE_MS, MOMENT_MS } from "@/lib/director.ts";
import { pendingApproval } from "@/lib/ledger.ts";
import { usd } from "@/lib/money.ts";
import { momentFor } from "@/lib/moments.ts";
import { latestPayloadFor } from "@/lib/payloads.ts";
import { attackerVisible } from "@/lib/strip.ts";
import type { XrayEvent } from "@/lib/xray.ts";
import { CaptionBar } from "./CaptionBar.tsx";
import { DetailsDrawer, type DetailsSelection } from "./DetailsDrawer.tsx";
import { DeviceStrip, type StripFocus } from "./DeviceStrip.tsx";
import { FitBox } from "./FitBox.tsx";
import { LedgerTakeover } from "./LedgerTakeover.tsx";
import { MomentBadge, MomentBanner } from "./MomentBanner.tsx";
import { NumbersRow } from "./NumbersRow.tsx";
import { AttackPanel } from "./panels/AttackPanel.tsx";
import { SatchelPanel } from "./panels/SatchelPanel.tsx";
import { SignerPanel } from "./panels/SignerPanel.tsx";
import { StorePanel } from "./panels/StorePanel.tsx";
import type { PlayedStep, Story } from "./useStory.ts";

/** True while `step` is younger than `ms`; re-renders when that flips. */
function useFresh(step: PlayedStep | null, ms: number): boolean {
  const [fresh, setFresh] = useState(false);
  useEffect(() => {
    if (!step || step.at === 0) {
      setFresh(false);
      return;
    }
    const left = ms - (Date.now() - step.at);
    if (left <= 0) {
      setFresh(false);
      return;
    }
    setFresh(true);
    const timer = setTimeout(() => setFresh(false), left);
    return () => clearTimeout(timer);
  }, [step, ms]);
  return fresh;
}

const CHAPTER_VISUAL: Partial<Record<Chapter, Visual>> = {
  satchel: "satchel",
  shopping: "store",
  attack: "attack",
  signer: "signer",
};

function StepControls({ story }: { story: Story }) {
  const auto = story.mode === "auto";
  const status =
    story.waiting > 0
      ? `${story.waiting} more step${story.waiting === 1 ? "" : "s"}`
      : story.reviewing
        ? "Reviewing an earlier step"
        : "Up to date";
  const canGo = story.waiting > 0 || story.reviewing;
  return (
    <div className="flex items-center gap-3">
      <span data-testid="step-status" className="text-[14px] text-muted">
        {auto ? "Auto-play" : status}
      </span>
      <button
        type="button"
        data-testid="step-back"
        aria-label="Previous step"
        onClick={story.back}
        disabled={story.played.length === 0 || story.current === story.played[0]}
        className="h-9 rounded-full border border-line bg-surface px-3.5 text-[14px] text-ink-soft transition hover:text-ink disabled:opacity-35"
      >
        ‹ Back
      </button>
      <button
        type="button"
        data-testid="step-next"
        aria-label="Next step"
        onClick={story.next}
        disabled={auto || !canGo}
        className={`h-9 rounded-full px-4 text-[14px] font-medium transition disabled:opacity-35 ${
          canGo && !auto
            ? "animate-glow bg-accent text-white hover:bg-accent-ink"
            : "border border-line bg-surface text-ink-soft"
        }`}
      >
        Next ›
      </button>
    </div>
  );
}

export default function XrayView({
  story,
  events,
  state,
  numbers,
}: {
  story: Story;
  events: XrayEvent[];
  state: XrayState | null;
  numbers: StoryNumbers;
}) {
  const { current, playheadSeq } = story;
  const { mainFundsSats, budget, lostSats, showLost } = numbers;
  const past = useMemo(
    () => events.filter((e) => e.seq <= playheadSeq),
    [events, playheadSeq],
  );
  const pending = pendingApproval(events, playheadSeq, state);
  const fresh = useFresh(current, IDLE_MS);
  const [details, setDetails] = useState<DetailsSelection | null>(null);

  let momentStep: PlayedStep | null = null;
  const upTo = current ? story.played.indexOf(current) : -1;
  for (let i = upTo; i >= 0; i--) {
    if (story.played[i].caption.moment) {
      momentStep = story.played[i];
      break;
    }
  }
  const bannerUp = useFresh(momentStep === current ? momentStep : null, MOMENT_MS);
  const moment = momentStep?.caption.moment
    ? momentFor(momentStep.caption.moment, momentStep.event, momentStep.ctx, mainFundsSats)
    : null;

  // A presenter may talk over a step for a while, and a step stepped back to is
  // looked at on purpose: keep its focus until they move on.
  const focused =
    current !== null &&
    (story.reviewing || (story.mode === "presenter" ? current.at > 0 : fresh));
  const focus: StripFocus | null =
    current && focused
      ? { key: current.key, nodes: current.caption.nodes, tone: current.caption.tone }
      : null;
  const caption = current?.caption ?? null;
  const visual: Visual | undefined =
    caption?.visual ?? (caption?.chapter ? CHAPTER_VISUAL[caption.chapter] : undefined);
  const ctx = current?.ctx ?? null;

  const openNode = (node: StripNode) =>
    setDetails({ node, payload: latestPayloadFor(events, node) });

  const strip = (compact: boolean) => (
    <DeviceStrip
      compact={compact}
      focus={focus}
      showAttacker={attackerVisible(past)}
      randomNonce={state?.random_nonce_signer === true}
      onNodeClick={openNode}
      agentSatchel={budget ? usd(budget.remainingSats) : null}
    />
  );

  return (
    <aside
      data-testid="xray-panel"
      className="relative flex h-full flex-col overflow-hidden border-l border-line bg-[#fbfaf8]"
    >
      <div className="relative shrink-0">
        <CaptionBar
          current={current}
          earlier={story.earlier}
          aside={
            <span className="flex shrink-0 items-center gap-2">
              {caption?.simulation && (
                <span
                  data-testid="simulation-chip"
                  className="rounded-full bg-bad-soft px-3 py-1 text-[13px] font-semibold tracking-wide text-bad uppercase"
                >
                  Simulation
                </span>
              )}
              {moment && !bannerUp && <MomentBadge moment={moment} />}
            </span>
          }
        />
        {moment && bannerUp && <MomentBanner key={momentStep?.key} moment={moment} />}
      </div>
      <div className="relative flex min-h-0 flex-1 flex-col">
        {pending ? (
          <LedgerTakeover key={pending.nonce ?? pending.text} pending={pending} />
        ) : visual && ctx ? (
          <>
            {strip(true)}
            <FitBox testId="stage-panel" data-visual={visual}>
              {visual === "satchel" && <SatchelPanel ctx={ctx} mainFundsSats={mainFundsSats} />}
              {visual === "store" && <StorePanel ctx={ctx} />}
              {visual === "attack" && <AttackPanel ctx={ctx} mainFundsSats={mainFundsSats} />}
              {visual === "signer" && <SignerPanel ctx={ctx} />}
            </FitBox>
          </>
        ) : (
          strip(false)
        )}
      </div>
      <NumbersRow
        mainFundsSats={mainFundsSats}
        budget={budget}
        lostSats={lostSats}
        showLost={showLost}
      />
      <footer data-testid="xray-footer" className="relative z-30 flex h-[52px] shrink-0 short:h-11 items-center justify-between border-t border-line bg-surface px-10">
        <button
          type="button"
          data-testid="details-toggle"
          aria-expanded={details !== null}
          onClick={() => setDetails((d) => (d ? null : { node: null, payload: null }))}
          className="flex items-center gap-2 text-[14px] font-medium text-ink-soft transition hover:text-ink"
        >
          Details
          <span className={`text-[12px] transition-transform ${details ? "rotate-180" : ""}`}>▲</span>
        </button>
        <StepControls story={story} />
      </footer>
      <DetailsDrawer
        events={events}
        open={details !== null}
        selection={details ?? { node: null, payload: null }}
        onSelect={(payload) => setDetails({ node: null, payload })}
        onNode={openNode}
      />
    </aside>
  );
}
