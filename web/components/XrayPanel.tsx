"use client";

import {
  useCallback,
  useEffect,
  useRef,
  useState,
  useSyncExternalStore,
  type RefObject,
} from "react";
import { xrayStore } from "@/lib/store.ts";
import { nowBanner } from "@/lib/now.ts";
import {
  eventAnimation,
  feedLabel,
  type XrayEvent,
} from "@/lib/xray.ts";
import {
  getState,
  mineBlock,
  runCompromise,
  setRandomNonce,
  type XrayState,
} from "@/lib/api.ts";
import { mergeState } from "@/lib/state.ts";
import { retryWhileBusy } from "@/lib/retry.ts";
import { Diagram, type DiagramAnim } from "@/components/xray/Diagram.tsx";
import { Story } from "@/components/xray/Story.tsx";
import { Guide } from "@/components/xray/Guide.tsx";
import {
  LedgerDevice,
  type DeviceHandle,
} from "@/components/xray/Device.tsx";
import {
  Balances,
  Controls,
  PayloadInspector,
} from "@/components/xray/Cards.tsx";

const LIVE_EVENT_MAX_AGE_MS = 60_000;
const ANIM_DOT_MS = 700;
const ANIM_FAST_MS = 350;
const ANIM_HOLD_MS = 850;

const BANNER_STYLES = {
  amber: "border-amber-300 bg-amber-50 text-amber-900",
  red: "border-red-300 bg-red-50 text-red-800",
  neutral: "border-neutral-200 bg-white text-neutral-600",
} as const;

export default function XrayPanel({
  open,
  sessionId,
  onClose,
  onSendMessage,
  deviceRef,
}: {
  open: boolean;
  sessionId: string | null;
  onClose: () => void;
  onSendMessage: (message: string) => void;
  deviceRef: RefObject<DeviceHandle | null>;
}) {
  const events = useSyncExternalStore(
    xrayStore.subscribe,
    () => xrayStore.snapshot,
    () => xrayStore.snapshot,
  );
  const [state, setState] = useState<XrayState | null>(null);
  const [selectedQr, setSelectedQr] = useState<XrayEvent | null>(null);
  const [dismissed, setDismissed] = useState<Set<number>>(new Set());
  const [active, setActive] = useState<DiagramAnim | null>(null);
  const [compromiseRunning, setCompromiseRunning] = useState(false);
  const [compromiseResult, setCompromiseResult] = useState<string | null>(
    null,
  );
  const [mineRunning, setMineRunning] = useState(false);
  const queueRef = useRef<XrayEvent[]>([]);
  const processingRef = useRef(false);
  const animKeyRef = useRef(0);
  const seenSeqRef = useRef(0);
  const inspectorRef = useRef<HTMLElement | null>(null);
  const refreshTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const refreshState = useCallback(() => {
    getState()
      .then((next) => setState((prev) => mergeState(prev, next)))
      .catch(() => {});
  }, []);

  const scheduleRefresh = useCallback(() => {
    if (refreshTimer.current) return;
    refreshTimer.current = setTimeout(() => {
      refreshTimer.current = null;
      refreshState();
    }, 400);
  }, [refreshState]);

  useEffect(() => {
    if (!open) return;
    const timer = setInterval(refreshState, 2000);
    refreshState();
    return () => clearInterval(timer);
  }, [open, refreshState]);

  const processQueue = useCallback(() => {
    if (processingRef.current) return;
    const next = queueRef.current.shift();
    if (!next) return;
    processingRef.current = true;
    const anim = eventAnimation(next);
    const key = ++animKeyRef.current;
    setActive({
      key,
      glow: anim.glow,
      edge: anim.edge,
      label: feedLabel(next),
      simulation: !!next.simulation,
    });
    const duration =
      queueRef.current.length > 3 ? ANIM_FAST_MS : ANIM_DOT_MS;
    setTimeout(() => {
      setActive(null);
      processingRef.current = false;
      processQueue();
    }, duration + ANIM_HOLD_MS);
  }, []);

  const lastBootRef = useRef<string | null>(null);

  useEffect(() => {
    const last = events[events.length - 1];
    if (!last) return;
    if (last.boot && last.boot !== lastBootRef.current) {
      lastBootRef.current = last.boot;
      seenSeqRef.current = 0;
    }
    const fresh = events.filter((e) => e.seq > seenSeqRef.current);
    if (fresh.length === 0) return;
    seenSeqRef.current = last.seq;
    const latestQr = [...fresh].reverse().find((e) => e.qr);
    if (latestQr) setSelectedQr(latestQr);
    for (const e of fresh) {
      const age = Date.now() - Date.parse(e.ts);
      if (Number.isFinite(age) && age >= 0 && age < LIVE_EVENT_MAX_AGE_MS) {
        queueRef.current.push(e);
      }
    }
    processQueue();
    if (open) scheduleRefresh();
  }, [events, open, processQueue, scheduleRefresh]);

  const latestQrEvent =
    selectedQr ?? [...events].reverse().find((e) => e.qr) ?? null;
  const recentQr = [...events]
    .reverse()
    .filter((e) => e.qr)
    .slice(0, 5);
  const alerts = events.filter(
    (e) => e.alert && !dismissed.has(e.seq),
  );

  const pending = state?.pending_approval?.pending ?? null;
  const banner = nowBanner({
    pendingText: pending?.text ?? null,
    events,
  });

  const showQr = useCallback((e: XrayEvent) => {
    setSelectedQr(e);
    inspectorRef.current?.scrollIntoView({
      behavior: "smooth",
      block: "center",
    });
  }, []);

  const compromise = useCallback(() => {
    if (!sessionId) return Promise.resolve();
    setCompromiseRunning(true);
    setCompromiseResult(null);
    return retryWhileBusy(() => runCompromise(sessionId))
      .then((r) => {
        const spend = r.large_spend as Record<string, unknown> | undefined;
        setCompromiseResult(
          `drained ${String(r.drained_sats)} sats · large spend ${
            spend?.broadcast
              ? "broadcast"
              : `blocked (${String(spend?.stage ?? "?")})`
          }`,
        );
      })
      .catch((err) =>
        setCompromiseResult(
          `failed: ${err instanceof Error ? err.message : "error"}`,
        ),
      )
      .finally(() => {
        setCompromiseRunning(false);
        refreshState();
      });
  }, [sessionId, refreshState]);

  const mine = useCallback(() => {
    setMineRunning(true);
    return mineBlock()
      .catch(() => {})
      .finally(() => {
        setMineRunning(false);
        refreshState();
      });
  }, [refreshState]);

  return (
    <aside
      data-testid="xray-panel"
      className="flex h-full flex-col border-l border-neutral-200 bg-neutral-50"
    >
      <div className="flex items-center justify-between border-b border-neutral-200 px-4 py-2.5">
        <div>
          <div className="text-sm font-semibold text-neutral-800">
            X-ray
          </div>
          <div className="text-[11px] text-neutral-400">
            what the agent is really doing
          </div>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="rounded-full px-2 py-1 text-xs text-neutral-400 hover:text-neutral-700"
          aria-label="Close x-ray"
        >
          ✕
        </button>
      </div>

      <div className="flex-1 overflow-y-auto">
        <div className="flex flex-col gap-3 p-3 min-[1200px]:flex-row min-[1200px]:items-start">
          <div className="order-2 min-w-0 space-y-3 min-[1200px]:order-1 min-[1200px]:w-[58%]">
            <Guide
              events={events}
              state={state}
              sessionId={sessionId}
              actions={{
                send: onSendMessage,
                mine,
                compromise,
                setRandomNonce: (enabled) => {
                  void setRandomNonce(enabled).then(refreshState);
                },
                focusDevice: () => deviceRef.current?.focus(),
              }}
            />

            <div
              data-testid="now-banner"
              className={`sticky top-0 z-10 rounded-xl border px-3 py-2 text-[12px] leading-snug shadow-sm ${BANNER_STYLES[banner.tone]}`}
            >
              {banner.text}
            </div>

            <section className="rounded-xl border border-neutral-200 bg-white p-3">
              <div className="mb-2 text-[11px] font-semibold tracking-wide text-neutral-400 uppercase">
                Devices
              </div>
              <Diagram state={state} active={active} />
            </section>

            {alerts.map((e) => (
              <div
                key={e.seq}
                data-testid="xray-alert"
                className="rounded-xl border border-red-300 bg-red-50 p-3"
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="text-xs font-semibold text-red-700">
                    {e.alert?.title}
                  </div>
                  <button
                    type="button"
                    onClick={() =>
                      setDismissed((d) => new Set(d).add(e.seq))
                    }
                    className="text-[10px] text-red-400 hover:text-red-700"
                    aria-label="Dismiss alert"
                  >
                    dismiss
                  </button>
                </div>
                <ul className="mt-1 list-disc pl-4 text-[11px] text-red-600">
                  {(e.alert?.reasons ?? []).map((r, i) => (
                    <li key={i}>{r}</li>
                  ))}
                </ul>
              </div>
            ))}

            <Story events={events} onShowQr={showQr} />
          </div>

          <div className="order-1 min-w-0 space-y-3 min-[1200px]:order-2 min-[1200px]:w-[42%]">
            <LedgerDevice
              ref={deviceRef}
              active={open}
              pending={
                pending
                  ? { kind: pending.kind, text: pending.text }
                  : null
              }
            />
            <Balances state={state} />
            <PayloadInspector
              event={latestQrEvent}
              recent={recentQr}
              onSelect={setSelectedQr}
              registerFocus={(el) => {
                inspectorRef.current = el;
              }}
            />
            <Controls
              state={state}
              sessionId={sessionId}
              onCompromise={() => void compromise()}
              compromiseRunning={compromiseRunning}
              compromiseResult={compromiseResult}
              onMine={mine}
              mineRunning={mineRunning}
              onRandomNonce={(enabled) => {
                void setRandomNonce(enabled).then(refreshState);
              }}
            />
          </div>
        </div>
      </div>
    </aside>
  );
}
