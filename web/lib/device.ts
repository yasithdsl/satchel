export const SCREEN_W = 480;
export const SCREEN_H = 600;
export const SWIPE_THRESHOLD_PX = 20;
export const HOLD_DELAY_MS = 150;
export const SWIPE_DELAY_S = 0.3;

export type GestureRelease =
  | { kind: "tap"; x: number; y: number }
  | { kind: "release"; x: number; y: number }
  | {
      kind: "swipe";
      x: number;
      y: number;
      x2: number;
      y2: number;
      delay: number;
    };

export function toDevicePoint(
  clientX: number,
  clientY: number,
  rect: { left: number; top: number; width: number; height: number },
): { x: number; y: number } {
  const x = Math.round(
    ((clientX - rect.left) / rect.width) * SCREEN_W,
  );
  const y = Math.round(
    ((clientY - rect.top) / rect.height) * SCREEN_H,
  );
  return {
    x: Math.min(Math.max(x, 0), SCREEN_W - 1),
    y: Math.min(Math.max(y, 0), SCREEN_H - 1),
  };
}

export function movedBeyondSwipe(
  dx: number,
  dy: number,
): boolean {
  return Math.hypot(dx, dy) > SWIPE_THRESHOLD_PX;
}

export function classifyRelease(
  start: { x: number; y: number },
  end: { x: number; y: number },
  pressSent: boolean,
): GestureRelease {
  if (pressSent) {
    return { kind: "release", x: start.x, y: start.y };
  }
  if (movedBeyondSwipe(end.x - start.x, end.y - start.y)) {
    return {
      kind: "swipe",
      x: start.x,
      y: start.y,
      x2: end.x,
      y2: end.y,
      delay: SWIPE_DELAY_S,
    };
  }
  return { kind: "tap", x: start.x, y: start.y };
}

export type ScreenKind = "blank" | "home" | "intro" | "review";

const HOME_SCREEN_RE = /^(quit app|this app enables signing)/i;
const INTRO_RE = /^(review message|swipe to review)/i;

/** What the emulated device shows; only a review is fit for the audience. */
export function screenKind(texts: string[]): ScreenKind {
  const clean = texts.map((t) => t.trim()).filter(Boolean);
  if (clean.length === 0) return "blank";
  if (clean.some((t) => HOME_SCREEN_RE.test(t))) return "home";
  if (clean.some((t) => INTRO_RE.test(t))) return "intro";
  return "review";
}
