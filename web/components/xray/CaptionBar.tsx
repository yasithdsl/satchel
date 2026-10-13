"use client";

import type { ReactNode } from "react";
import type { Tone } from "@/lib/caption.ts";
import type { PlayedStep } from "./useStory.ts";

const MARKER: Record<Tone, string> = {
  neutral: "bg-accent",
  good: "bg-good",
  bad: "bg-bad",
};

export function CaptionBar({
  played,
  aside,
}: {
  played: PlayedStep[];
  aside?: ReactNode;
}) {
  const current = played[played.length - 1] ?? null;
  const earlier = played.slice(-3, -1).reverse();
  return (
    <section
      data-testid="caption-bar"
      className="shrink-0 border-b border-line px-10 pt-7 pb-6"
    >
      <div className="mb-3 flex h-8 items-center justify-between gap-4">
        <span className="text-[13px] font-semibold tracking-[0.16em] text-muted uppercase">
          X-ray · What just happened
        </span>
        {aside}
      </div>
      <div className="min-h-[2.5em] text-[clamp(26px,1.75vw,34px)] leading-[1.2]">
       <div className="flex gap-4">
        <span
          className={`my-[0.12em] w-1.5 shrink-0 rounded-full ${
            current ? MARKER[current.caption.tone] : "bg-line"
          }`}
        />
        {current ? (
          <p
            key={current.key}
            data-testid="caption"
            data-tone={current.caption.tone}
            className={`animate-rise line-clamp-3 font-semibold ${
              current.caption.tone === "bad" ? "text-bad" : "text-ink"
            }`}
          >
            {current.caption.text}
          </p>
        ) : (
          <p data-testid="caption" className="font-semibold text-muted">
            Waiting for your first request.
          </p>
        )}
       </div>
      </div>
      <div className="mt-3 h-[3.2em] space-y-1 pl-[22px] text-[clamp(16px,1vw,19px)] leading-[1.45]">
        {earlier.map((step, i) => (
          <p
            key={step.key}
            data-testid="caption-earlier"
            className={`truncate text-ink-soft ${i === 0 ? "opacity-60" : "opacity-35"}`}
          >
            {step.caption.text}
          </p>
        ))}
      </div>
    </section>
  );
}
