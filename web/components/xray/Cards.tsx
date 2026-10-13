"use client";

import { useEffect, useRef, useState } from "react";
import QRCode from "qrcode";
import { nextIndex, partAt } from "@/lib/qr.ts";
import { satsToUsd } from "@/lib/story.ts";
import { feedLabel, feedTime, type XrayEvent } from "@/lib/xray.ts";
import type { XrayState } from "@/lib/api.ts";

function fmtSats(sats: number | null | undefined): string {
  if (sats == null) return "—";
  return `${(sats / 100_000_000).toFixed(8)} BTC`;
}

function envelopeLabel(e: {
  status: string;
  assigned_to: string | null;
}): string {
  switch (e.status) {
    case "unfunded":
      return "not funded";
    case "drained":
      return "empty";
    case "assigned":
    case "spent":
      return e.assigned_to ? `in use by ${e.assigned_to}` : "in use";
    default:
      return "available";
  }
}

export function Balances({ state }: { state: XrayState | null }) {
  return (
    <section
      className="rounded-xl border border-neutral-200 bg-white p-3"
      data-testid="balances"
    >
      <div className="mb-2 text-[11px] font-semibold tracking-wide text-neutral-400 uppercase">
        Balances
      </div>
      <div className="space-y-2 text-xs">
        <div>
          <div className="flex justify-between">
            <span className="text-neutral-600">Main funds</span>
            <span className="font-mono text-neutral-800">
              {fmtSats(state?.main_funds?.balance_sats)}
            </span>
          </div>
          {state?.main_funds && (
            <div className="mt-0.5 text-right text-[10px] text-neutral-400">
              {satsToUsd(state.main_funds.balance_sats)} ·{" "}
              {satsToUsd(state.main_funds.available_sats)} available
            </div>
          )}
        </div>
        {(state?.envelopes ?? []).map((e) => {
          const balance = e.balance_sats ?? 0;
          const available = e.available_sats ?? balance;
          const pct =
            e.budget_sats > 0
              ? Math.max(0, Math.min(100, (available / e.budget_sats) * 100))
              : 0;
          return (
            <div key={e.index}>
              <div className="flex items-baseline justify-between">
                <span className="text-neutral-600">
                  Envelope {e.index}
                  <span className="ml-1 text-[10px] text-neutral-400">
                    {envelopeLabel(e)}
                  </span>
                </span>
                <span
                  className="font-mono text-[11px] text-neutral-800"
                  data-testid={`envelope-${e.index}-available`}
                >
                  {satsToUsd(available)} / {satsToUsd(e.budget_sats)}
                </span>
              </div>
              <div className="mt-0.5 h-1 overflow-hidden rounded-full bg-neutral-100">
                <div
                  className="h-full rounded-full bg-sky-400 transition-all"
                  style={{ width: `${pct}%` }}
                />
              </div>
              {available < balance && (
                <div className="mt-0.5 text-right text-[10px] text-amber-600">
                  {satsToUsd(balance - available)} pending block
                </div>
              )}
            </div>
          );
        })}
        {state?.loss_sink && (
          <div className="flex justify-between text-red-700">
            <span>Loss sink (attacker)</span>
            <span className="font-mono">
              {satsToUsd(
                state.loss_sink.confirmed_sats +
                  state.loss_sink.pending_sats,
              )}
            </span>
          </div>
        )}
      </div>
    </section>
  );
}

export function PayloadInspector({
  event,
  recent,
  onSelect,
  registerFocus,
}: {
  event: XrayEvent | null;
  recent: XrayEvent[];
  onSelect: (e: XrayEvent) => void;
  registerFocus?: (el: HTMLElement | null) => void;
}) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const [partIdx, setPartIdx] = useState(0);
  const parts = event?.qr?.parts ?? [];

  useEffect(() => {
    setPartIdx(0);
  }, [event?.id]);

  useEffect(() => {
    if (parts.length <= 1) return;
    const timer = setInterval(
      () => setPartIdx((i) => nextIndex(parts, i)),
      600,
    );
    return () => clearInterval(timer);
  }, [parts]);

  useEffect(() => {
    const part = partAt(parts, partIdx);
    if (!part || !canvasRef.current) return;
    void QRCode.toCanvas(canvasRef.current, part, {
      width: 170,
      margin: 1,
      errorCorrectionLevel: "L",
    });
  }, [parts, partIdx]);

  return (
    <section
      ref={registerFocus}
      className="rounded-xl border border-neutral-200 bg-white p-3"
      data-testid="payload-inspector"
    >
      <div className="mb-2 text-[11px] font-semibold tracking-wide text-neutral-400 uppercase">
        Payload inspector
      </div>
      {event?.qr ? (
        <div className="flex items-start gap-3">
          <canvas
            ref={canvasRef}
            data-testid="qr-canvas"
            className="h-[150px] w-[150px] shrink-0"
          />
          <div className="min-w-0 flex-1 space-y-1.5">
            <div className="text-xs leading-snug text-neutral-700">
              {feedLabel(event)}
            </div>
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="rounded bg-neutral-100 px-1.5 py-0.5 text-[10px] text-neutral-500">
                {event.qr.type}
              </span>
              {event.qr.redacted && (
                <span className="rounded bg-amber-100 px-1.5 py-0.5 text-[10px] font-medium text-amber-700">
                  keys hidden
                </span>
              )}
              {parts.length > 1 && (
                <span className="text-[10px] text-neutral-400">
                  part {partIdx + 1}/{parts.length}
                </span>
              )}
            </div>
          </div>
        </div>
      ) : (
        <div className="text-xs text-neutral-400">
          No boundary payloads yet — approvals and key handoffs appear
          here as QR codes.
        </div>
      )}
      {recent.length > 1 && (
        <div className="mt-2 space-y-0.5 border-t border-neutral-100 pt-2">
          {recent.map((e) => (
            <button
              key={e.id}
              type="button"
              onClick={() => onSelect(e)}
              className={`block w-full truncate rounded px-1.5 py-0.5 text-left text-[11px] transition ${
                e.id === event?.id
                  ? "bg-sky-50 text-sky-800"
                  : "text-neutral-500 hover:bg-neutral-50"
              }`}
            >
              <span className="mr-1 font-mono text-[9px] text-neutral-300">
                {feedTime(e.ts)}
              </span>
              {feedLabel(e)}
            </button>
          ))}
        </div>
      )}
    </section>
  );
}

export function Controls({
  state,
  sessionId,
  onCompromise,
  compromiseRunning,
  compromiseResult,
  onMine,
  mineRunning,
  onRandomNonce,
}: {
  state: XrayState | null;
  sessionId: string | null;
  onCompromise: () => void;
  compromiseRunning: boolean;
  compromiseResult: string | null;
  onMine: () => void;
  mineRunning: boolean;
  onRandomNonce: (enabled: boolean) => void;
}) {
  return (
    <details className="rounded-xl border border-neutral-200 bg-white p-3">
      <summary className="cursor-pointer text-[11px] font-semibold tracking-wide text-neutral-400 uppercase select-none">
        Demo controls
      </summary>
      <div className="mt-2.5">
        <label className="flex items-center justify-between text-xs text-neutral-600">
          <span>Malicious signer (random nonce) · demo</span>
          <input
            type="checkbox"
            data-testid="random-nonce-toggle"
            checked={state?.random_nonce_signer ?? false}
            disabled={state?.random_nonce_signer == null}
            onChange={(e) => onRandomNonce(e.target.checked)}
            className="h-3.5 w-3.5 accent-red-500"
          />
        </label>
        <div className="mt-1 text-[10px] text-neutral-400">
          makes the signer produce valid but non-deterministic
          signatures — the vault refuses to broadcast them
        </div>
        <div className="mt-2 flex gap-2">
          <button
            type="button"
            data-testid="compromise-button"
            disabled={
              !sessionId ||
              !state?.compromise_control?.enabled ||
              compromiseRunning
            }
            onClick={onCompromise}
            className="flex-1 rounded-lg border border-amber-300 bg-amber-50 px-2 py-1.5 text-[11px] font-medium text-amber-800 transition hover:bg-amber-100 disabled:opacity-40"
          >
            {compromiseRunning
              ? "Running simulation…"
              : "Simulate compromised agent"}
          </button>
          <button
            type="button"
            data-testid="mine-button"
            disabled={mineRunning}
            onClick={onMine}
            className="rounded-lg border border-neutral-200 px-2 py-1.5 text-[11px] text-neutral-600 transition hover:bg-neutral-100 disabled:opacity-40"
          >
            {mineRunning ? "Mining…" : "Mine block"}
          </button>
        </div>
        <div className="mt-1 text-[10px] text-amber-600">
          SIMULATION only — no real compromise happens
        </div>
        {compromiseResult && (
          <div
            data-testid="compromise-result"
            className="mt-1 rounded bg-neutral-100 px-2 py-1 text-[11px] text-neutral-700"
          >
            {compromiseResult}
          </div>
        )}
      </div>
    </details>
  );
}
