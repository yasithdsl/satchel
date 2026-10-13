import type { Caption } from "./caption.ts";

/** How long a caption stays before the next one, so a room can read it. */
export const DWELL_MS = 1_900;
/** A big moment holds the story for this long, then becomes a badge. */
export const MOMENT_MS = 6_000;
/** Events older than this on arrival (a reload) are shown, not replayed. */
export const LIVE_WINDOW_MS = 60_000;
/** After this long with nothing new, the strip stops dimming. */
export const IDLE_MS = 9_000;

export function dwellMs(caption: Caption, waiting: number): number {
  if (caption.moment) return MOMENT_MS;
  if (waiting >= 6) return 450;
  if (waiting >= 3) return 950;
  return DWELL_MS;
}

export function isLive(ts: string, now: number): boolean {
  const age = now - Date.parse(ts);
  return Number.isFinite(age) && age < LIVE_WINDOW_MS;
}
