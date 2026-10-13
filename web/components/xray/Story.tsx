"use client";

import { storyLine, type StoryKind, type StoryTone } from "@/lib/story.ts";
import {
  componentColor,
  feedLabel,
  feedTime,
  type XrayEvent,
} from "@/lib/xray.ts";

const KIND_BADGE: Record<StoryKind, string> = {
  agent: "A",
  ledger: "L",
  vault: "V",
  laptop: "P",
  signer: "S",
  shop: "$",
  network: "#",
  attack: "!",
};

const KIND_STYLE: Record<StoryKind, string> = {
  agent: "bg-violet-100 text-violet-700",
  ledger: "bg-emerald-100 text-emerald-700",
  vault: "bg-amber-100 text-amber-700",
  laptop: "bg-sky-100 text-sky-700",
  signer: "bg-orange-100 text-orange-700",
  shop: "bg-teal-100 text-teal-700",
  network: "bg-neutral-100 text-neutral-600",
  attack: "bg-red-100 text-red-700",
};

const TONE_STYLE: Record<StoryTone, string> = {
  neutral: "text-neutral-700",
  good: "text-emerald-800",
  warn: "text-amber-800",
  bad: "text-red-700",
  sim: "text-amber-800",
};

export function Story({
  events,
  onShowQr,
}: {
  events: XrayEvent[];
  onShowQr: (e: XrayEvent) => void;
}) {
  const story = [...events]
    .reverse()
    .map((e) => ({ e, line: storyLine(e) }))
    .filter((x) => x.line !== null);

  return (
    <section className="rounded-xl border border-neutral-200 bg-white p-3">
      <div className="mb-2 text-[11px] font-semibold tracking-wide text-neutral-400 uppercase">
        Story
      </div>
      <div className="space-y-1.5" data-testid="story-feed">
        {story.length === 0 && (
          <div className="text-[11px] text-neutral-400">
            Nothing has happened yet — the story starts when the agent
            acts.
          </div>
        )}
        {story.map(({ e, line }) => (
          <div
            key={e.seq}
            className="flex items-start gap-2 text-[12px]"
          >
            <span
              className={`mt-px flex h-4 w-4 shrink-0 items-center justify-center rounded text-[9px] font-bold ${KIND_STYLE[line!.kind]}`}
            >
              {KIND_BADGE[line!.kind]}
            </span>
            <span className={`min-w-0 flex-1 leading-snug ${TONE_STYLE[line!.tone]}`}>
              {line!.text}
              {e.simulation && line!.tone !== "sim" && (
                <span className="ml-1 rounded bg-amber-100 px-1 py-px text-[9px] font-semibold text-amber-700">
                  SIMULATION
                </span>
              )}
            </span>
            {e.qr && (
              <button
                type="button"
                onClick={() => onShowQr(e)}
                className="shrink-0 rounded border border-neutral-200 px-1 py-px text-[9px] text-neutral-500 transition hover:bg-neutral-50"
                aria-label="Show payload QR"
              >
                QR
              </button>
            )}
            <span className="w-12 shrink-0 text-right font-mono text-[9px] text-neutral-300">
              {feedTime(e.ts)}
            </span>
          </div>
        ))}
      </div>

      <details className="mt-3 border-t border-neutral-100 pt-2">
        <summary className="cursor-pointer text-[10px] font-medium text-neutral-400 select-none">
          Developer log
        </summary>
        <div className="mt-2 max-h-64 space-y-1 overflow-y-auto" data-testid="event-feed">
          {[...events].reverse().map((e) => (
            <div key={e.seq} className="flex items-start gap-1.5 text-[11px]">
              <span className="w-14 shrink-0 font-mono text-neutral-300">
                {feedTime(e.ts)}
              </span>
              <span
                className={`shrink-0 rounded px-1 py-px text-[9px] font-medium ${componentColor(e.component)}`}
              >
                {e.component}
              </span>
              <span className="min-w-0 flex-1 leading-snug text-neutral-600">
                {feedLabel(e)}
                {e.simulation && (
                  <span className="ml-1 rounded bg-amber-100 px-1 py-px text-[9px] font-semibold text-amber-700">
                    SIMULATION
                  </span>
                )}
              </span>
            </div>
          ))}
        </div>
      </details>
    </section>
  );
}
