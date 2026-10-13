"use client";

import type { ReactNode } from "react";
import type { Chapter, Tone } from "@/lib/caption.ts";
import type { PlayedStep } from "./useStory.ts";

const MARKER: Record<Tone, string> = {
  neutral: "bg-accent",
  good: "bg-good",
  bad: "bg-bad",
};

export const CHAPTER_LABEL: Record<Chapter, string> = {
  satchel: "Creating a satchel",
  shopping: "Shopping inside the satchel",
  payment: "Paying from main funds",
  attack: "Simulated attack: a compromised agent",
  signer: "Simulated attack: a rigged signer",
};

/**
 * A steady minimum height so the stage below doesn't jump from step to step; it
 * only grows when a long caption needs the room.
 */
const MIN_HEIGHT = "min-h-[clamp(160px,23vh,262px)]";

export function CaptionBar({
  current,
  earlier,
  aside,
}: {
  current: PlayedStep | null;
  earlier: PlayedStep[];
  aside?: ReactNode;
}) {
  const caption = current?.caption ?? null;
  const step = caption?.step;
  return (
    <section
      data-testid="caption-bar"
      className={`flex shrink-0 flex-col overflow-hidden border-b border-line px-10 pt-6 pb-3 short:pt-4 short:pb-2 ${MIN_HEIGHT}`}
    >
      <div className="mb-3 flex h-8 shrink-0 items-center justify-between gap-4 short:mb-2">
        <div className="flex min-w-0 items-center gap-4">
          <span
            data-testid="chapter"
            className={`truncate text-[13px] font-semibold tracking-[0.16em] uppercase ${
              caption?.simulation ? "text-bad" : "text-muted"
            }`}
          >
            {caption?.chapter ? CHAPTER_LABEL[caption.chapter] : "Under the hood"}
          </span>
          {step && (
            <span data-testid="chapter-step" className="flex shrink-0 items-center gap-2 text-[13px] text-muted">
              <span className="flex gap-1">
                {Array.from({ length: step.total }, (_, i) => (
                  <span
                    key={i}
                    className={`h-1.5 w-4 rounded-full ${i < step.index ? "bg-accent" : "bg-line"}`}
                  />
                ))}
              </span>
              Step {step.index} of {step.total}
            </span>
          )}
        </div>
        {aside}
      </div>
      <div className="flex shrink-0 gap-4">
        <span
          className={`my-[0.2em] w-1.5 shrink-0 rounded-full ${caption ? MARKER[caption.tone] : "bg-line"}`}
        />
        <div className="min-w-0">
          {caption ? (
            <p
              key={current!.key}
              data-testid="caption"
              data-tone={caption.tone}
              className={`animate-rise line-clamp-2 text-[clamp(26px,2vw,40px)] leading-[1.15] font-semibold ${
                caption.tone === "bad" ? "text-bad" : "text-ink"
              }`}
            >
              {caption.text}
            </p>
          ) : (
            <p data-testid="caption" className="text-[clamp(26px,2vw,40px)] leading-[1.15] font-semibold text-muted">
              Waiting for your first request.
            </p>
          )}
          {caption?.why && (
            <p
              key={`why-${current!.key}`}
              data-testid="caption-why"
              className="animate-rise mt-2 line-clamp-2 text-[clamp(17px,1.15vw,22px)] leading-snug text-ink-soft"
            >
              {caption.why}
            </p>
          )}
        </div>
      </div>
      {/* Earlier lines fill whatever room is left, newest at the bottom. A line that
          doesn't fit whole wraps into a second column, out of sight. */}
      <div className="mt-2 flex h-0 min-h-0 flex-1 flex-col-reverse flex-wrap content-start overflow-hidden pl-[22px]">
        {earlier.map((s, i) => (
          <p
            key={s.key}
            data-testid="caption-earlier"
            className={`w-full shrink-0 truncate text-[15px] leading-6 text-ink-soft ${i === 0 ? "opacity-55" : "opacity-30"}`}
          >
            {s.caption.text}
          </p>
        ))}
      </div>
    </section>
  );
}
