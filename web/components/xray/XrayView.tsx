"use client";

import { useEffect, useState } from "react";
import type { XrayState } from "@/lib/api.ts";
import type { BudgetView } from "@/lib/balances.ts";
import type { StripNode } from "@/lib/caption.ts";
import { IDLE_MS, MOMENT_MS } from "@/lib/director.ts";
import { pendingApproval } from "@/lib/ledger.ts";
import { momentFor } from "@/lib/moments.ts";
import { latestPayloadFor } from "@/lib/payloads.ts";
import { attackerVisible } from "@/lib/strip.ts";
import type { XrayEvent } from "@/lib/xray.ts";
import { CaptionBar } from "./CaptionBar.tsx";
import { DetailsDrawer, type DetailsSelection } from "./DetailsDrawer.tsx";
import { DeviceStrip, type StripFocus } from "./DeviceStrip.tsx";
import { LedgerTakeover } from "./LedgerTakeover.tsx";
import { MomentBadge, MomentBanner } from "./MomentBanner.tsx";
import { NumbersRow } from "./NumbersRow.tsx";
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

export default function XrayView({
  story,
  events,
  state,
  budget,
  mainFundsSats,
  lostSats,
  showLost,
}: {
  story: Story;
  events: XrayEvent[];
  state: XrayState | null;
  budget: BudgetView | null;
  mainFundsSats: number | null;
  lostSats: number;
  showLost: boolean;
}) {
  const { played, current, playheadSeq } = story;
  const pending = pendingApproval(events, playheadSeq, state);
  const active = useFresh(current, IDLE_MS);
  const [details, setDetails] = useState<DetailsSelection | null>(null);

  let momentStep: PlayedStep | null = null;
  for (let i = played.length - 1; i >= 0; i--) {
    if (played[i].caption.moment) {
      momentStep = played[i];
      break;
    }
  }
  const bannerUp = useFresh(momentStep, MOMENT_MS);
  const moment = momentStep?.caption.moment
    ? momentFor(momentStep.caption.moment, momentStep.event, momentStep.ctx, mainFundsSats)
    : null;

  const focus: StripFocus | null =
    current && active
      ? { key: current.key, nodes: current.caption.nodes, tone: current.caption.tone }
      : null;
  const simulation = current?.ctx.compromiseActive ?? false;

  const openNode = (node: StripNode) =>
    setDetails({ node, payload: latestPayloadFor(events, node) });

  return (
    <aside
      data-testid="xray-panel"
      className="relative flex h-full flex-col overflow-hidden border-l border-line bg-[#fbfaf8]"
    >
      <CaptionBar
        played={played}
        aside={
          <span className="flex items-center gap-2">
            {simulation && (
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
      <div className="relative min-h-0 flex-1">
        {pending ? (
          <LedgerTakeover key={pending.nonce ?? pending.text} pending={pending} />
        ) : (
          <DeviceStrip
            focus={focus}
            showAttacker={attackerVisible(events)}
            randomNonce={state?.random_nonce_signer === true}
            onNodeClick={openNode}
          />
        )}
      </div>
      <NumbersRow
        mainFundsSats={mainFundsSats}
        budget={budget}
        lostSats={lostSats}
        showLost={showLost}
      />
      <DetailsDrawer
        events={events}
        open={details !== null}
        selection={details ?? { node: null, payload: null }}
        onToggle={() =>
          setDetails((d) => (d ? null : { node: null, payload: null }))
        }
        onSelect={(payload) => setDetails({ node: null, payload })}
        onNode={openNode}
      />
    </aside>
  );
}
