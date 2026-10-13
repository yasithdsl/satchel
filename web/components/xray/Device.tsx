"use client";

import {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useRef,
  useState,
} from "react";
import {
  classifyRelease,
  HOLD_DELAY_MS,
  movedBeyondSwipe,
  screenHint,
  toDevicePoint,
} from "@/lib/device.ts";
import {
  getLedgerAutomation,
  getLedgerScreenText,
  ledgerAction,
  ledgerScreenshotUrl,
  postFinger,
} from "@/lib/api.ts";

const POLL_SCREEN_MS = 400;
const POLL_TEXT_MS = 600;
const DEVICE_W = 480;
const DEVICE_H = 600;

export interface DeviceHandle {
  focus: () => void;
}

interface Press {
  start: { x: number; y: number };
  last: { x: number; y: number };
  moved: boolean;
  fired: boolean;
  timer: ReturnType<typeof setTimeout> | null;
}

export const LedgerDevice = forwardRef<
  DeviceHandle,
  {
    active: boolean;
    pending: { kind: string; text: string } | null;
  }
>(function LedgerDevice({ active, pending }, ref) {
  const [image, setImage] = useState<string | null>(null);
  const [screenTexts, setScreenTexts] = useState<string[]>([]);
  const hint = screenHint(screenTexts, !!pending);
  const [automation, setAutomation] = useState<boolean | null>(null);
  const [actionBusy, setActionBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const cardRef = useRef<HTMLDivElement | null>(null);
  const imgRef = useRef<HTMLImageElement | null>(null);
  const pressRef = useRef<Press | null>(null);

  const focus = useCallback(() => {
    cardRef.current?.scrollIntoView({
      behavior: "smooth",
      block: "center",
    });
  }, []);
  useImperativeHandle(ref, () => ({ focus }), [focus]);

  useEffect(() => {
    if (!active) return;
    let cancelled = false;
    let url: string | null = null;
    const poll = async () => {
      while (!cancelled) {
        try {
          const res = await fetch(
            `${ledgerScreenshotUrl()}?t=${Date.now()}`,
            { cache: "no-store" },
          );
          if (res.ok) {
            const blob = await res.blob();
            const next = URL.createObjectURL(blob);
            if (cancelled) {
              URL.revokeObjectURL(next);
            } else {
              if (url) URL.revokeObjectURL(url);
              url = next;
              setImage(next);
            }
          }
        } catch {
        }
        await new Promise((r) => setTimeout(r, POLL_SCREEN_MS));
      }
    };
    void poll();
    return () => {
      cancelled = true;
      if (url) URL.revokeObjectURL(url);
    };
  }, [active]);

  useEffect(() => {
    if (!active) return;
    let cancelled = false;
    const poll = async () => {
      while (!cancelled) {
        try {
          const texts = await getLedgerScreenText();
          if (!cancelled) setScreenTexts(texts);
        } catch {
        }
        await new Promise((r) => setTimeout(r, POLL_TEXT_MS));
      }
    };
    void poll();
    return () => {
      cancelled = true;
    };
  }, [active]);

  useEffect(() => {
    if (!active || automation !== null) return;
    void getLedgerAutomation().then(setAutomation);
  }, [active, automation]);

  const wasPending = useRef(false);
  useEffect(() => {
    if (pending && !wasPending.current) focus();
    wasPending.current = !!pending;
  }, [pending, focus]);

  const devPoint = (e: React.PointerEvent) => {
    const rect = imgRef.current?.getBoundingClientRect();
    if (!rect) return { x: 0, y: 0 };
    return toDevicePoint(e.clientX, e.clientY, rect);
  };

  const onPointerDown = (e: React.PointerEvent) => {
    if (pressRef.current || !imgRef.current) return;
    e.currentTarget.setPointerCapture(e.pointerId);
    const start = devPoint(e);
    const state: Press = {
      start,
      last: start,
      moved: false,
      fired: false,
      timer: null,
    };
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
    if (
      !state.moved &&
      movedBeyondSwipe(p.x - state.start.x, p.y - state.start.y)
    ) {
      state.moved = true;
      if (state.timer) clearTimeout(state.timer);
    }
  };

  const endPress = (e: React.PointerEvent, cancelled: boolean) => {
    const state = pressRef.current;
    if (!state) return;
    pressRef.current = null;
    if (state.timer) clearTimeout(state.timer);
    if (cancelled && !state.fired) return;
    if (cancelled && state.fired) {
      void postFinger({
        action: "release",
        x: state.start.x,
        y: state.start.y,
      });
      return;
    }
    const gesture = classifyRelease(state.start, state.last, state.fired);
    if (gesture.kind === "tap") {
      void postFinger({
        action: "press-and-release",
        x: gesture.x,
        y: gesture.y,
      });
    } else if (gesture.kind === "swipe") {
      void postFinger({
        action: "press-and-release",
        x: gesture.x,
        y: gesture.y,
        x2: gesture.x2,
        y2: gesture.y2,
        delay: gesture.delay,
      });
    } else {
      void postFinger({
        action: "release",
        x: gesture.x,
        y: gesture.y,
      });
    }
  };

  const swipePage = (forward: boolean) => {
    void postFinger({
      action: "press-and-release",
      x: forward ? DEVICE_W - 80 : 80,
      y: DEVICE_H / 2,
      x2: forward ? 80 : DEVICE_W - 80,
      y2: DEVICE_H / 2,
      delay: 0.3,
    });
  };

  const doAction = (action: "approve" | "reject") => {
    setActionBusy(true);
    setActionError(null);
    void ledgerAction(action).then((r) => {
      setActionBusy(false);
      if (r.status === 409) {
        setAutomation(false);
      } else if (!r.ok) {
        setActionError(
          `${action === "approve" ? "Approve" : "Reject"} failed (${r.status})`,
        );
      }
    });
  };

  return (
    <div
      ref={cardRef}
      data-testid="ledger-device"
      className={`rounded-2xl bg-neutral-950 p-3 transition-shadow duration-500 ${
        pending
          ? "shadow-[0_0_0_2px_#f59e0b,0_0_24px_rgba(245,158,11,0.45)]"
          : "shadow-[0_0_0_1px_#292524]"
      }`}
    >
      <div className="mb-2 flex items-center justify-between px-1">
        <span className="text-[11px] font-semibold tracking-wide text-neutral-400 uppercase">
          Ledger
        </span>
        <span
          data-testid="device-hint"
          className={`text-[11px] ${
            pending ? "text-amber-300" : "text-neutral-500"
          }`}
        >
          {hint}
        </span>
      </div>

      {pending && (
        <div
          data-testid="device-pending"
          className="mb-2 rounded-lg border border-amber-500/40 bg-amber-500/10 px-2.5 py-2 text-[11px] whitespace-pre-wrap text-amber-100"
        >
          {pending.text}
        </div>
      )}

      <div className="mx-auto w-full max-w-[300px]">
        <div className="rounded-[2rem] border border-neutral-700 bg-black p-2">
          <div
            className="relative overflow-hidden rounded-2xl bg-neutral-900"
            style={{ aspectRatio: `${DEVICE_W} / ${DEVICE_H}` }}
          >
            {image ? (
              <img
                ref={imgRef}
                src={image}
                alt="Ledger screen"
                data-testid="device-screen"
                draggable={false}
                className="h-full w-full touch-none object-contain select-none"
                onPointerDown={onPointerDown}
                onPointerMove={onPointerMove}
                onPointerUp={(e) => endPress(e, false)}
                onPointerCancel={(e) => endPress(e, true)}
              />
            ) : (
              <div className="flex h-full items-center justify-center text-xs text-neutral-600">
                connecting…
              </div>
            )}
          </div>
        </div>
        <div className="mt-2 flex items-center justify-between gap-2">
          <button
            type="button"
            aria-label="Previous page"
            onClick={() => swipePage(false)}
            className="rounded-full border border-neutral-700 px-3 py-1 text-neutral-300 transition hover:bg-neutral-800"
          >
            ‹
          </button>
          <div className="flex flex-1 gap-2">
            <button
              type="button"
              data-testid="device-approve"
              disabled={!automation || actionBusy}
              onClick={() => doAction("approve")}
              className="flex-1 rounded-full bg-emerald-600 px-2 py-1.5 text-[11px] font-semibold text-white transition hover:bg-emerald-500 disabled:opacity-40"
            >
              Approve on device
            </button>
            <button
              type="button"
              data-testid="device-reject"
              disabled={!automation || actionBusy}
              onClick={() => doAction("reject")}
              className="flex-1 rounded-full bg-red-700 px-2 py-1.5 text-[11px] font-semibold text-white transition hover:bg-red-600 disabled:opacity-40"
            >
              Reject on device
            </button>
          </div>
          <button
            type="button"
            aria-label="Next page"
            onClick={() => swipePage(true)}
            className="rounded-full border border-neutral-700 px-3 py-1 text-neutral-300 transition hover:bg-neutral-800"
          >
            ›
          </button>
        </div>
        {automation === false && (
          <div
            data-testid="automation-hint"
            className="mt-1.5 text-center text-[10px] text-neutral-500"
          >
            automation is off — approve by tapping and holding on the
            screen
          </div>
        )}
        {actionError && (
          <div className="mt-1.5 text-center text-[10px] text-red-400">
            {actionError}
          </div>
        )}
        <div className="mt-1.5 text-center text-[10px] text-neutral-600">
          tap, swipe or press-and-hold the screen like the real device
        </div>
      </div>
    </div>
  );
});
