"use client";

import type { Moment } from "@/lib/moments.ts";
import { CheckIcon, ShieldIcon } from "@/components/icons";

/** Covers the caption bar exactly: render it in the caption bar's positioned wrapper. */
export function MomentBanner({ moment }: { moment: Moment }) {
  const good = moment.tone === "good";
  return (
    <div
      data-testid="moment-banner"
      data-kind={moment.kind}
      className={`animate-rise absolute inset-0 z-40 flex items-center gap-6 border-b-4 px-10 py-6 short:py-4 ${
        good ? "border-good bg-good-soft text-good" : "border-bad bg-bad-soft text-bad"
      }`}
    >
      <span
        className={`flex h-16 w-16 shrink-0 items-center justify-center rounded-full text-white ${
          good ? "bg-good" : "bg-bad"
        }`}
      >
        {good ? <CheckIcon className="h-9 w-9" /> : <ShieldIcon className="h-9 w-9" />}
      </span>
      <p className="text-[clamp(26px,2vw,40px)] leading-[1.2] font-semibold">
        {moment.text}
      </p>
    </div>
  );
}

export function MomentBadge({ moment }: { moment: Moment }) {
  const good = moment.tone === "good";
  return (
    <span
      data-testid="moment-badge"
      data-kind={moment.kind}
      className={`animate-rise inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-[13px] font-semibold ${
        good ? "bg-good-soft text-good" : "bg-bad-soft text-bad"
      }`}
    >
      {good ? <CheckIcon className="h-4 w-4" /> : <ShieldIcon className="h-4 w-4" />}
      {moment.badge}
    </span>
  );
}
