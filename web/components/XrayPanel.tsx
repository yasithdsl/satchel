"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import QRCode from "qrcode";
import {
  componentColor,
  eventAnimation,
  feedLabel,
  feedTime,
  NODE_LABELS,
  type NodeId,
  type XrayEvent,
} from "@/lib/xray.ts";
import { nextIndex, partAt } from "@/lib/qr.ts";
import {
  getState,
  mineBlock,
  runCompromise,
  setRandomNonce,
  SPECULOS_URL,
  streamXrayEvents,
  type XrayState,
} from "@/lib/api.ts";

const NODE_POS: Record<NodeId, { x: number; y: number }> = {
  agent: { x: 78, y: 52 },
  ledger: { x: 342, y: 52 },
  envelope: { x: 78, y: 168 },
  laptop: { x: 210, y: 222 },
  marketplace: { x: 78, y: 352 },
  vault: { x: 342, y: 322 },
  signer: { x: 342, y: 432 },
  losssink: { x: 200, y: 466 },
};

const STATIC_EDGES: [NodeId, NodeId][] = [
  ["agent", "envelope"],
  ["agent", "laptop"],
  ["agent", "marketplace"],
  ["envelope", "laptop"],
  ["envelope", "marketplace"],
  ["envelope", "losssink"],
  ["laptop", "ledger"],
  ["laptop", "vault"],
  ["laptop", "signer"],
  ["laptop", "marketplace"],
];

const LIVE_EVENT_MAX_AGE_MS = 60_000;

interface ActiveAnim {
  key: number;
  glow: string[];
  edge: { from: string; to: string } | null;
  simulation: boolean;
}

function Diagram({ active }: { active: ActiveAnim | null }) {
  const glowing = new Set(active?.glow ?? []);
  const edge = active?.edge ?? null;
  const edgeEnds = edge
    ? {
        x1: NODE_POS[edge.from as NodeId]?.x ?? 0,
        y1: NODE_POS[edge.from as NodeId]?.y ?? 0,
        x2: NODE_POS[edge.to as NodeId]?.x ?? 0,
        y2: NODE_POS[edge.to as NodeId]?.y ?? 0,
      }
    : null;

  return (
    <svg viewBox="0 0 420 500" className="h-auto w-full">
      {STATIC_EDGES.map(([a, b]) => (
        <line
          key={`${a}-${b}`}
          x1={NODE_POS[a].x}
          y1={NODE_POS[a].y}
          x2={NODE_POS[b].x}
          y2={NODE_POS[b].y}
          stroke={b === "losssink" ? "#fca5a5" : "#e7e5e4"}
          strokeWidth="1.5"
          strokeDasharray={b === "losssink" ? "4 3" : undefined}
        />
      ))}
      {edgeEnds && (
        <circle
          key={active?.key}
          r="5"
          fill={active?.simulation ? "#f59e0b" : "#0ea5e9"}
          data-testid="hop-dot"
        >
          <animateMotion
            dur="0.7s"
            fill="freeze"
            path={`M ${edgeEnds.x1} ${edgeEnds.y1} L ${edgeEnds.x2} ${edgeEnds.y2}`}
          />
        </circle>
      )}
      {(Object.keys(NODE_POS) as NodeId[]).map((id) => {
        const { x, y } = NODE_POS[id];
        const isAttacker = id === "losssink";
        const glow = glowing.has(id);
        return (
          <g key={id} data-testid={`node-${id}`} data-glow={glow || undefined}>
            <rect
              x={x - 44}
              y={y - 16}
              width="88"
              height="32"
              rx="10"
              fill={isAttacker ? "#fef2f2" : glow ? "#eef9ff" : "#ffffff"}
              stroke={
                glow ? "#38bdf8" : isAttacker ? "#fca5a5" : "#d6d3d1"
              }
              strokeWidth={glow ? 2.5 : 1.5}
              style={
                glow
                  ? { filter: "drop-shadow(0 0 6px rgba(56,189,248,0.8))" }
                  : undefined
              }
            />
            <text
              x={x}
              y={y + 4}
              textAnchor="middle"
              fontSize="11"
              fill={isAttacker ? "#b91c1c" : "#44403c"}
              fontWeight={glow ? 600 : 500}
            >
              {NODE_LABELS[id]}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

function BoundaryPayload({
  event,
  recent,
  onSelect,
}: {
  event: XrayEvent | null;
  recent: XrayEvent[];
  onSelect: (e: XrayEvent) => void;
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
    <section className="rounded-xl border border-neutral-200 bg-white p-3">
      <div className="mb-2 text-[11px] font-semibold tracking-wide text-neutral-400 uppercase">
        Boundary payload
      </div>
      {event?.qr ? (
        <div className="flex items-start gap-3">
          <canvas
            ref={canvasRef}
            data-testid="qr-canvas"
            className="h-[170px] w-[170px] shrink-0"
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
          No boundary payloads yet — approvals and key handoffs appear here
          as QR codes.
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
              {feedLabel(e)}
            </button>
          ))}
        </div>
      )}
    </section>
  );
}

function fmtSats(sats: number | null | undefined): string {
  if (sats == null) return "—";
  return `${(sats / 100_000_000).toFixed(8)} BTC`;
}

function Balances({ state }: { state: XrayState | null }) {
  return (
    <section className="rounded-xl border border-neutral-200 bg-white p-3">
      <div className="mb-2 text-[11px] font-semibold tracking-wide text-neutral-400 uppercase">
        Balances
      </div>
      <div className="space-y-1.5 text-xs">
        <div className="flex justify-between">
          <span className="text-neutral-600">Main funds</span>
          <span className="font-mono text-neutral-800">
            {fmtSats(state?.main_funds?.balance_sats)}
          </span>
        </div>
        {(state?.envelopes ?? []).map((e) => (
          <div key={e.index} className="flex items-baseline justify-between">
            <span className="text-neutral-600">
              Envelope {e.index}
              <span className="ml-1 text-[10px] text-neutral-400">
                {e.assigned_to ?? "unassigned"} · {e.status}
              </span>
            </span>
            <span className="font-mono text-neutral-800">
              {fmtSats(e.balance_sats)}
              <span className="ml-1 text-[10px] text-neutral-400">
                / {fmtSats(e.budget_sats)}
              </span>
            </span>
          </div>
        ))}
        {state?.loss_sink && (
          <div className="flex justify-between text-red-700">
            <span>Loss sink (attacker)</span>
            <span className="font-mono">
              {fmtSats(
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

export default function XrayPanel({
  open,
  sessionId,
  onClose,
}: {
  open: boolean;
  sessionId: string | null;
  onClose: () => void;
}) {
  const [feed, setFeed] = useState<XrayEvent[]>([]);
  const [state, setState] = useState<XrayState | null>(null);
  const [selectedQr, setSelectedQr] = useState<XrayEvent | null>(null);
  const [dismissed, setDismissed] = useState<Set<number>>(new Set());
  const [active, setActive] = useState<ActiveAnim | null>(null);
  const [compromiseRunning, setCompromiseRunning] = useState(false);
  const [compromiseResult, setCompromiseResult] = useState<string | null>(null);
  const [mineRunning, setMineRunning] = useState(false);
  const queueRef = useRef<XrayEvent[]>([]);
  const processingRef = useRef(false);
  const animKeyRef = useRef(0);

  const refreshState = useCallback(() => {
    getState()
      .then(setState)
      .catch(() => {});
  }, []);

  useEffect(() => {
    if (!open) return;
    const timer = setInterval(refreshState, 2000);
    refreshState();
    return () => clearInterval(timer);
  }, [open, refreshState]);

  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    void (async () => {
      try {
        for await (const msg of streamXrayEvents(controller.signal, 200)) {
          const event = JSON.parse(msg.data) as XrayEvent;
          setFeed((f) => [event, ...f].slice(0, 300));
          if (event.qr) {
            setSelectedQr(event);
          }
          const age = Date.now() - Date.parse(event.ts);
          if (Number.isFinite(age) && age >= 0 && age < LIVE_EVENT_MAX_AGE_MS) {
            queueRef.current.push(event);
            processQueue();
          }
          refreshState();
        }
      } catch {
        if (controller.signal.aborted) return;
      }
    })();
    return () => controller.abort();
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
      simulation: !!next.simulation,
    });
    const duration = queueRef.current.length > 3 ? 350 : 700;
    setTimeout(() => {
      setActive(null);
      processingRef.current = false;
      processQueue();
    }, duration + 250);
  }, []);

  const latestQrEvent = selectedQr ?? feed.find((e) => e.qr) ?? null;
  const recentQr = feed.filter((e) => e.qr).slice(0, 5);
  const alerts = feed.filter(
    (e) => e.alert && !dismissed.has(e.seq),
  );

  return (
    <aside
      data-testid="xray-panel"
      className={`fixed top-0 right-0 z-20 flex h-full w-[26rem] flex-col border-l border-neutral-200 bg-neutral-50 shadow-2xl transition-transform duration-300 ${
        open ? "translate-x-0" : "translate-x-full"
      }`}
    >
      <div className="flex items-center justify-between border-b border-neutral-200 px-4 py-3">
        <div>
          <div className="text-sm font-semibold text-neutral-800">X-ray</div>
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

      <div className="flex-1 space-y-3 overflow-y-auto p-3">
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

        <section className="rounded-xl border border-neutral-200 bg-white p-3">
          <div className="mb-2 text-[11px] font-semibold tracking-wide text-neutral-400 uppercase">
            Devices
          </div>
          <Diagram active={active} />
        </section>

        <BoundaryPayload
          event={latestQrEvent}
          recent={recentQr}
          onSelect={setSelectedQr}
        />

        <section className="rounded-xl border border-neutral-200 bg-white p-3">
          <div className="mb-2 text-[11px] font-semibold tracking-wide text-neutral-400 uppercase">
            Ledger
          </div>
          {state?.pending_approval?.pending ? (
            <div className="mb-2 rounded-lg border border-amber-200 bg-amber-50 p-2 text-[11px] whitespace-pre-wrap text-amber-900">
              {state.pending_approval.pending.text}
            </div>
          ) : (
            <div className="mb-2 text-[11px] text-neutral-400">
              No pending approval — the device is idle.
            </div>
          )}
          <div className="h-[200px] overflow-hidden rounded-lg border border-neutral-100 bg-neutral-900">
            <iframe
              title="Ledger (Speculos)"
              src={SPECULOS_URL}
              className="h-[300px] w-[640px] origin-top-left scale-[0.62]"
            />
          </div>
        </section>

        <Balances state={state} />

        <section className="rounded-xl border border-neutral-200 bg-white p-3">
          <div className="mb-2 text-[11px] font-semibold tracking-wide text-neutral-400 uppercase">
            Demo controls
          </div>
          <label className="flex items-center justify-between text-xs text-neutral-600">
            <span>Malicious signer (random nonce) · demo</span>
            <input
              type="checkbox"
              data-testid="random-nonce-toggle"
              checked={state?.random_nonce_signer ?? false}
              disabled={state?.random_nonce_signer == null}
              onChange={(e) => {
                const enabled = e.target.checked;
                void setRandomNonce(enabled).then(refreshState);
              }}
              className="h-3.5 w-3.5 accent-red-500"
            />
          </label>
          <div className="mt-2 flex gap-2">
            <button
              type="button"
              data-testid="compromise-button"
              disabled={
                !sessionId ||
                !state?.compromise_control?.enabled ||
                compromiseRunning
              }
              onClick={() => {
                if (!sessionId) return;
                setCompromiseRunning(true);
                setCompromiseResult(null);
                void runCompromise(sessionId)
                  .then((r) => {
                    const spend = r.large_spend as
                      | Record<string, unknown>
                      | undefined;
                    setCompromiseResult(
                      `drained ${String(r.drained_sats)} sats · large spend ${
                        spend?.broadcast ? "broadcast" : `blocked (${String(spend?.stage ?? "?")})`
                      }`,
                    );
                  })
                  .catch((err) =>
                    setCompromiseResult(
                      `failed: ${err instanceof Error ? err.message : "error"}`,
                    ),
                  )
                  .finally(() => setCompromiseRunning(false));
              }}
              className="flex-1 rounded-lg border border-amber-300 bg-amber-50 px-2 py-1.5 text-[11px] font-medium text-amber-800 transition hover:bg-amber-100 disabled:opacity-40"
            >
              {compromiseRunning
                ? "Running simulation…"
                : "Simulate compromised agent"}
            </button>
            <button
              type="button"
              disabled={mineRunning}
              onClick={() => {
                setMineRunning(true);
                void mineBlock()
                  .catch(() => {})
                  .finally(() => {
                    setMineRunning(false);
                    refreshState();
                  });
              }}
              className="rounded-lg border border-neutral-200 px-2 py-1.5 text-[11px] text-neutral-600 transition hover:bg-neutral-100 disabled:opacity-40"
            >
              {mineRunning ? "Mining…" : "Mine block"}
            </button>
          </div>
          <div className="mt-1 text-[10px] text-amber-600">
            simulation only — no real compromise happens
          </div>
          {compromiseResult && (
            <div
              data-testid="compromise-result"
              className="mt-1 rounded bg-neutral-100 px-2 py-1 text-[11px] text-neutral-700"
            >
              {compromiseResult}
            </div>
          )}
        </section>

        <section className="rounded-xl border border-neutral-200 bg-white p-3">
          <div className="mb-2 text-[11px] font-semibold tracking-wide text-neutral-400 uppercase">
            Event feed
          </div>
          <div className="space-y-1" data-testid="event-feed">
            {feed.length === 0 && (
              <div className="text-[11px] text-neutral-400">
                Waiting for events…
              </div>
            )}
            {feed.map((e) => (
              <div key={e.seq} className="flex items-start gap-1.5 text-[11px]">
                <span className="w-14 shrink-0 font-mono text-neutral-300">
                  {feedTime(e.ts)}
                </span>
                <span
                  className={`shrink-0 rounded px-1 py-px text-[9px] font-medium ${componentColor(e.component)}`}
                >
                  {e.component}
                </span>
                <span className="min-w-0 flex-1 leading-snug text-neutral-600">
                  {feedLabel(e)}
                  {e.simulation && (
                    <span className="ml-1 rounded bg-amber-100 px-1 py-px text-[9px] font-semibold text-amber-700">
                      SIMULATION
                    </span>
                  )}
                </span>
              </div>
            ))}
          </div>
        </section>
      </div>
    </aside>
  );
}
