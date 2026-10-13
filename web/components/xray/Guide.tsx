"use client";

import { useEffect, useMemo, useState } from "react";
import {
  advance,
  currentStep,
  SCENARIOS,
  scenarioById,
  startScenario,
  type GuideAction,
  type GuideProgress,
} from "@/lib/guide.ts";
import { satsToUsd } from "@/lib/story.ts";
import type { XrayState } from "@/lib/api.ts";
import type { XrayEvent } from "@/lib/xray.ts";

export interface GuideActions {
  send: (message: string) => void;
  mine: () => void;
  compromise: () => void | Promise<unknown>;
  setRandomNonce: (enabled: boolean) => void;
  focusDevice: () => void;
}

export function Guide({
  events,
  state,
  sessionId,
  actions,
}: {
  events: XrayEvent[];
  state: XrayState | null;
  sessionId: string | null;
  actions: GuideActions;
}) {
  const [progress, setProgress] = useState<
    Record<string, GuideProgress>
  >({});
  const [activeId, setActiveId] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const lastSeq = events.length
    ? events[events.length - 1].seq
    : 0;

  useEffect(() => {
    const last = events[events.length - 1];
    if (!last) return;
    setProgress((prev) => {
      let changed = false;
      const next = { ...prev };
      for (const [id, p] of Object.entries(prev)) {
        const advanced = advance(p, last);
        if (advanced !== p) {
          next[id] = advanced;
          changed = true;
        }
      }
      return changed ? next : prev;
    });
  }, [events]);

  const runAction = (stepId: string, action: GuideAction) => {
    switch (action.kind) {
      case "send":
        if (action.message) actions.send(action.message);
        break;
      case "mine":
        actions.mine();
        break;
      case "compromise":
        setBusy(stepId);
        Promise.resolve(actions.compromise()).finally(() =>
          setBusy(null),
        );
        break;
      case "random-on":
        actions.setRandomNonce(true);
        break;
      case "random-off":
        actions.setRandomNonce(false);
        break;
      case "device":
        actions.focusDevice();
        break;
    }
  };

  const active = activeId ? progress[activeId] : undefined;

  const summary = useMemo(() => {
    if (!state) return null;
    const sink = state.loss_sink;
    const sinkSats =
      (sink?.confirmed_sats ?? 0) + (sink?.pending_sats ?? 0);
    const envelopes = state.envelopes ?? [];
    const spent = envelopes.find((e) => e.assigned_to);
    const untouched =
      state.main_funds != null &&
      state.main_funds.available_sats ===
        state.main_funds.balance_sats;
    return {
      sinkSats,
      envelope: spent ?? null,
      envelopeAvailable:
        spent == null
          ? null
          : (spent.available_sats ?? spent.balance_sats),
      untouched,
    };
  }, [state]);

  return (
    <details
      open
      className="rounded-xl border border-neutral-200 bg-white p-3"
      data-testid="demo-guide"
    >
      <summary className="cursor-pointer text-[11px] font-semibold tracking-wide text-neutral-400 uppercase select-none">
        Demo guide
      </summary>
      <div className="mt-2 flex gap-1.5">
        {SCENARIOS.map((s) => {
          const p = progress[s.id];
          const isActive = activeId === s.id;
          return (
            <button
              key={s.id}
              type="button"
              onClick={() => {
                setActiveId(s.id);
                setProgress((prev) =>
                  prev[s.id]
                    ? prev
                    : { ...prev, [s.id]: startScenario(s.id, lastSeq) },
                );
              }}
              className={`flex-1 rounded-lg border px-2 py-1.5 text-left text-[10px] font-medium transition ${
                isActive
                  ? "border-sky-300 bg-sky-50 text-sky-800"
                  : "border-neutral-200 text-neutral-500 hover:bg-neutral-50"
              }`}
            >
              {s.title}
              {p?.done && <span className="ml-1 text-emerald-600">✓</span>}
            </button>
          );
        })}
      </div>

      {activeId && active && (
        <div className="mt-2.5" data-testid="guide-steps">
          <div className="mb-2 text-[11px] leading-snug text-neutral-500">
            {scenarioById(activeId)?.intro}
          </div>
          <ol className="space-y-1.5">
            {scenarioById(activeId)?.steps.map((step, i) => {
              const isCurrent = i === active.stepIndex && !active.done;
              const isDone =
                i < active.stepIndex || (active.done && i <= active.stepIndex);
              const needsSession =
                step.action?.kind === "compromise" && !sessionId;
              return (
                <li
                  key={step.id}
                  data-testid={`guide-step-${step.id}`}
                  data-done={isDone || undefined}
                  data-current={isCurrent || undefined}
                  className={`flex items-start gap-2 rounded-lg px-2 py-1.5 text-[11px] leading-snug ${
                    isCurrent
                      ? "bg-sky-50 text-neutral-800"
                      : isDone
                        ? "text-neutral-400"
                        : "text-neutral-500"
                  }`}
                >
                  <span
                    className={`mt-0.5 flex h-3.5 w-3.5 shrink-0 items-center justify-center rounded-full border text-[9px] ${
                      isDone
                        ? "border-emerald-400 bg-emerald-100 text-emerald-700"
                        : isCurrent
                          ? "border-sky-400 text-sky-600"
                          : "border-neutral-300 text-neutral-300"
                    }`}
                  >
                    {isDone ? "✓" : i + 1}
                  </span>
                  <span className="min-w-0 flex-1">{step.text}</span>
                  {isCurrent && step.action && (
                    <button
                      type="button"
                      data-testid={`guide-action-${step.id}`}
                      disabled={needsSession || busy === step.id}
                      onClick={() => runAction(step.id, step.action!)}
                      className="shrink-0 rounded-full border border-sky-300 bg-white px-2 py-0.5 text-[10px] font-medium text-sky-700 transition hover:bg-sky-50 disabled:opacity-40"
                    >
                      {busy === step.id
                        ? "Running…"
                        : step.action.label}
                    </button>
                  )}
                  {isCurrent && needsSession && (
                    <span className="shrink-0 text-[9px] text-neutral-400">
                      needs a chat session
                    </span>
                  )}
                </li>
              );
            })}
          </ol>

          {activeId === "compromise" &&
            (currentStep(active)?.auto || active.done) &&
            summary && (
              <div
                data-testid="guide-compromise-result"
                className="mt-2 rounded-lg border border-amber-200 bg-amber-50 px-2.5 py-2 text-[11px] text-amber-900"
              >
                The attacker took {satsToUsd(summary.sinkSats)} to the
                loss sink.
                {summary.envelope &&
                  ` The envelope was the limit — ${satsToUsd(summary.envelopeAvailable ?? 0)} left of its ${satsToUsd(summary.envelope.budget_sats)} budget.`}
                {summary.untouched
                  ? " Main funds untouched."
                  : " Main funds changed — check the balances."}
              </div>
            )}
          {active.done && (
            <div className="mt-2 rounded-lg bg-emerald-50 px-2.5 py-1.5 text-[11px] font-medium text-emerald-700">
              Scenario complete.
            </div>
          )}
        </div>
      )}
      {!activeId && (
        <div className="mt-2 text-[11px] text-neutral-400">
          Pick a scenario — each step lights up as the system does it.
        </div>
      )}
    </details>
  );
}
