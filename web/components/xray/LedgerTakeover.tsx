"use client";

import { useEffect, useRef, useState } from "react";
import {
  classifyRelease,
  HOLD_DELAY_MS,
  movedBeyondSwipe,
  screenKind,
  SCREEN_H,
  SCREEN_W,
  toDevicePoint,
} from "@/lib/device.ts";
import {
  getLedgerAutomation,
  getLedgerScreenText,
  ledgerAction,
  ledgerScreenshotUrl,
  postFinger,
} from "@/lib/api.ts";
import { planSummary, type PendingApproval } from "@/lib/ledger.ts";
import { CheckIcon } from "@/components/icons";

const POLL_SCREEN_MS = 400;
const POLL_TEXT_MS = 500;

interface Press {
  start: { x: number; y: number };
  last: { x: number; y: number };
  moved: boolean;
  fired: boolean;
  timer: ReturnType<typeof setTimeout> | null;
}

function swipe(forward: boolean) {
  return postFinger({
    action: "press-and-release",
    x: forward ? SCREEN_W - 80 : 80,
    y: SCREEN_H / 2,
    x2: forward ? 80 : SCREEN_W - 80,
    y2: SCREEN_H / 2,
    delay: 0.3,
  });
}

export function LedgerTakeover({ pending }: { pending: PendingApproval }) {
  const [image, setImage] = useState<string | null>(null);
  const [texts, setTexts] = useState<string[]>([]);
  const [automation, setAutomation] = useState<boolean | null>(null);
  const [acting, setActing] = useState<"approve" | "reject" | null>(null);
  const [trouble, setTrouble] = useState(false);
  const imgRef = useRef<HTMLImageElement | null>(null);
  const pressRef = useRef<Press | null>(null);
  const advancedRef = useRef<string | null>(null);

  const kind = screenKind(texts);
  const showScreen = image !== null && (kind === "intro" || kind === "review");
  const summary = planSummary(pending);

  useEffect(() => {
    let cancelled = false;
    let url: string | null = null;
    void (async () => {
      while (!cancelled) {
        try {
          const res = await fetch(`${ledgerScreenshotUrl()}?t=${Date.now()}`, {
            cache: "no-store",
          });
          if (res.ok) {
            const next = URL.createObjectURL(await res.blob());
            if (cancelled) URL.revokeObjectURL(next);
            else {
              if (url) URL.revokeObjectURL(url);
              url = next;
              setImage(next);
            }
          }
        } catch (err) {
          console.debug("ledger screenshot unavailable", err);
        }
        await new Promise((r) => setTimeout(r, POLL_SCREEN_MS));
      }
    })();
    return () => {
      cancelled = true;
      if (url) URL.revokeObjectURL(url);
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      while (!cancelled) {
        const next = await getLedgerScreenText().catch(() => []);
        if (!cancelled) setTexts(next);
        await new Promise((r) => setTimeout(r, POLL_TEXT_MS));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    void getLedgerAutomation().then(setAutomation);
  }, []);

  // Step past the "Review message" cover once, so the plan text itself is on screen.
  useEffect(() => {
    const id = pending.nonce ?? pending.text;
    if (kind !== "intro" || advancedRef.current === id || acting) return;
    advancedRef.current = id;
    void swipe(true);
  }, [kind, pending.nonce, pending.text, acting]);

  const devPoint = (e: React.PointerEvent) => {
    const rect = imgRef.current?.getBoundingClientRect();
    if (!rect) return { x: 0, y: 0 };
    return toDevicePoint(e.clientX, e.clientY, rect);
  };

  const onPointerDown = (e: React.PointerEvent) => {
    if (pressRef.current || !imgRef.current) return;
    e.currentTarget.setPointerCapture(e.pointerId);
    const start = devPoint(e);
    const state: Press = { start, last: start, moved: false, fired: false, timer: null };
    state.timer = setTimeout(() => {
      if (!state.moved) {
        state.fired = true;
        void postFinger({ action: "press", x: start.x, y: start.y });
      }
    }, HOLD_DELAY_MS);
    pressRef.current = state;
  };

  const onPointerMove = (e: React.PointerEvent) => {
    const state = pressRef.current;
    if (!state) return;
    const p = devPoint(e);
    state.last = p;
    if (!state.moved && movedBeyondSwipe(p.x - state.start.x, p.y - state.start.y)) {
      state.moved = true;
      if (state.timer) clearTimeout(state.timer);
    }
  };

  const endPress = (cancelled: boolean) => {
    const state = pressRef.current;
    if (!state) return;
    pressRef.current = null;
    if (state.timer) clearTimeout(state.timer);
    if (cancelled) {
      if (state.fired) void postFinger({ action: "release", ...state.start });
      return;
    }
    const g = classifyRelease(state.start, state.last, state.fired);
    if (g.kind === "tap") {
      void postFinger({ action: "press-and-release", x: g.x, y: g.y });
    } else if (g.kind === "swipe") {
      void postFinger({
        action: "press-and-release",
        x: g.x,
        y: g.y,
        x2: g.x2,
        y2: g.y2,
        delay: g.delay,
      });
    } else {
      void postFinger({ action: "release", x: g.x, y: g.y });
    }
  };

  const decide = (action: "approve" | "reject") => {
    setActing(action);
    setTrouble(false);
    void ledgerAction(action).then((result) => {
      if (result.ok) return;
      setActing(null);
      if (result.reason === "nothing_pending") return;
      if (result.reason === "automation_off") {
        setAutomation(false);
        return;
      }
      console.warn("[satchel] ledger:", result.detail);
      setTrouble(true);
    });
  };

  return (
    <div
      data-testid="ledger-takeover"
      className="animate-rise flex h-full items-center justify-center gap-12 px-10 py-5"
    >
      <div className="flex h-full max-h-[620px] min-h-0 flex-col items-center">
        <div className="flex min-h-0 flex-1 items-center">
          <div
            data-testid="ledger-device"
            className="flex h-full max-h-full flex-col rounded-[38px] bg-[#141414] p-3.5 shadow-[0_24px_60px_-20px_rgb(0_0_0/0.45)]"
          >
            <div
              className="relative h-full overflow-hidden rounded-[26px] bg-[#0b0b0b]"
              style={{ aspectRatio: `${SCREEN_W} / ${SCREEN_H}` }}
            >
              {showScreen ? (
                <img
                  ref={imgRef}
                  src={image!}
                  alt="Ledger screen"
                  data-testid="device-screen"
                  draggable={false}
                  className="h-full w-full touch-none object-contain select-none"
                  onPointerDown={onPointerDown}
                  onPointerMove={onPointerMove}
                  onPointerUp={() => endPress(false)}
                  onPointerCancel={() => endPress(true)}
                />
              ) : (
                <div
                  data-testid="device-waiting"
                  className="flex h-full flex-col items-center justify-center gap-4 px-8 text-center text-[17px] text-white/70"
                >
                  <span className="flex gap-1.5">
                    {[0, 1, 2].map((i) => (
                      <span
                        key={i}
                        className="animate-blink h-2 w-2 rounded-full bg-white/70"
                        style={{ animationDelay: `${i * 0.2}s` }}
                      />
                    ))}
                  </span>
                  Sending the plan to your Ledger…
                </div>
              )}
            </div>
          </div>
        </div>
        <div className="mt-5 flex shrink-0 items-center gap-3">
          <button
            type="button"
            aria-label="Previous page"
            onClick={() => void swipe(false)}
            className="h-12 w-12 rounded-full border border-line bg-surface text-[22px] text-ink-soft transition hover:text-ink"
          >
            ‹
          </button>
          {automation !== false && (
            <>
              <button
                type="button"
                data-testid="device-reject"
                disabled={!automation || acting !== null || !showScreen}
                onClick={() => decide("reject")}
                className="h-12 min-w-[132px] rounded-2xl border border-[#2a2a2a] bg-[#1c1c1c] px-5 text-[16px] font-semibold text-white shadow-[inset_0_-3px_0_rgb(0_0_0/0.5),0_2px_0_rgb(0_0_0/0.15)] transition hover:bg-[#262626] active:translate-y-px disabled:opacity-40"
              >
                {acting === "reject" ? "Rejecting…" : "Reject"}
              </button>
              <button
                type="button"
                data-testid="device-approve"
                disabled={!automation || acting !== null || !showScreen}
                onClick={() => decide("approve")}
                className="inline-flex h-12 min-w-[132px] items-center justify-center gap-2 rounded-2xl border border-[#2a2a2a] bg-[#1c1c1c] px-5 text-[16px] font-semibold text-white shadow-[inset_0_-3px_0_rgb(0_0_0/0.5),0_2px_0_rgb(0_0_0/0.15)] transition hover:bg-[#262626] active:translate-y-px disabled:opacity-40"
              >
                <CheckIcon className="h-4 w-4 text-[#4ade80]" />
                {acting === "approve" ? "Approving…" : "Approve"}
              </button>
            </>
          )}
          <button
            type="button"
            aria-label="Next page"
            onClick={() => void swipe(true)}
            className="h-12 w-12 rounded-full border border-line bg-surface text-[22px] text-ink-soft transition hover:text-ink"
          >
            ›
          </button>
        </div>
      </div>

      <div className="max-w-[360px] min-w-0">
        <div className="text-[13px] font-semibold tracking-[0.16em] text-muted uppercase">
          On your Ledger
        </div>
        <p
          data-testid="takeover-headline"
          className="mt-3 text-[clamp(24px,1.6vw,30px)] leading-tight font-semibold text-ink"
        >
          {summary.headline}
        </p>
        {summary.detail && (
          <p className="mt-2 text-[18px] leading-snug text-ink-soft">{summary.detail}</p>
        )}
        <p className="mt-7 text-[20px] leading-snug text-ink">
          Read it on the device, then approve or reject.
        </p>
        {automation === false && (
          <p className="mt-3 text-[16px] text-ink-soft">
            Tap and hold on the device screen to answer.
          </p>
        )}
        {trouble && (
          <p data-testid="ledger-trouble" className="mt-3 text-[16px] text-ink-soft">
            The Ledger didn&apos;t respond. Try again.
          </p>
        )}
        <p className="mt-8 border-t border-line pt-4 text-[13px] leading-relaxed text-muted">
          Emulated Ledger. Each approval is a signed message the vault verifies
          before releasing keys.
        </p>
      </div>
    </div>
  );
}
