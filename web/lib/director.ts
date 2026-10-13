import type { Caption } from "./caption.ts";

/** How long a step stays in auto-play before the next one. */
export const DWELL_MS = 3_400;
/** A big moment's banner shows this long, then shrinks to a badge. */
export const MOMENT_MS = 6_000;
/** Events older than this on arrival (a reload) are shown, not replayed. */
export const LIVE_WINDOW_MS = 60_000;
/** After this long with nothing new, the strip stops dimming. */
export const IDLE_MS = 12_000;

export type PaceMode = "presenter" | "auto";

export function dwellMs(caption: Caption, waiting: number): number {
  if (caption.moment) return MOMENT_MS;
  if (waiting >= 8) return 900;
  if (waiting >= 4) return 1_800;
  return DWELL_MS;
}

export function isLive(ts: string, now: number): boolean {
  const age = now - Date.parse(ts);
  return Number.isFinite(age) && age < LIVE_WINDOW_MS;
}

/** Keys a presenter or a clicker sends to move through the story. */
export function stepKey(key: string): "next" | "back" | null {
  if (key === "ArrowRight" || key === " " || key === "PageDown") return "next";
  if (key === "ArrowLeft" || key === "PageUp") return "back";
  return null;
}
