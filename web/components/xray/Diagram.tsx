"use client";

import {
  EDGES,
  NODE_POS,
  NODES,
  ZONES,
  nodeValue,
} from "@/lib/diagram.ts";
import type { XrayState } from "@/lib/api.ts";
import type { NodeId } from "@/lib/xray.ts";

export interface DiagramAnim {
  key: number;
  glow: string[];
  edge: { from: string; to: string } | null;
  label: string | null;
  simulation: boolean;
}

const ZONE_STYLES: Record<string, string> = {
  neutral: "border-neutral-200 bg-white/60",
  warn: "border-amber-200 bg-amber-50/50",
  danger: "border-red-200 bg-red-50/50",
};

const ZONE_LABEL_STYLES: Record<string, string> = {
  neutral: "text-neutral-400",
  warn: "text-amber-500",
  danger: "text-red-400",
};

export function Diagram({
  state,
  active,
}: {
  state: XrayState | null;
  active: DiagramAnim | null;
}) {
  const glowing = new Set(active?.glow ?? []);
  const edge = active?.edge ?? null;
  const pending = !!state?.pending_approval?.pending;

  return (
    <div
      data-testid="diagram"
      className="relative w-full"
      style={{ aspectRatio: "5 / 3.4" }}
    >
      {ZONES.map((z) => (
        <div
          key={z.id}
          className={`absolute rounded-xl border ${ZONE_STYLES[z.tone]}`}
          style={{
            left: `${z.left}%`,
            top: `${z.top}%`,
            width: `${z.width}%`,
            height: `${z.height}%`,
          }}
        >
          <span
            className={`absolute top-1 left-2 text-[9px] font-semibold tracking-widest uppercase ${ZONE_LABEL_STYLES[z.tone]}`}
          >
            {z.label}
          </span>
        </div>
      ))}

      <svg
        className="absolute inset-0 h-full w-full"
        viewBox="0 0 100 100"
        preserveAspectRatio="none"
      >
        {EDGES.map(([a, b]) => (
          <line
            key={`${a}-${b}`}
            x1={NODE_POS[a].x}
            y1={NODE_POS[a].y}
            x2={NODE_POS[b].x}
            y2={NODE_POS[b].y}
            stroke={b === "losssink" ? "#fca5a5" : "#e7e5e4"}
            strokeWidth="0.4"
            strokeDasharray={b === "losssink" ? "2 1.5" : undefined}
            vectorEffect="non-scaling-stroke"
          />
        ))}
        {edge && (
          <circle
            key={active?.key}
            r="1.6"
            fill={active?.simulation ? "#f59e0b" : "#0ea5e9"}
            data-testid="hop-dot"
          >
            <animateMotion
              dur="0.7s"
              fill="freeze"
              path={`M ${NODE_POS[edge.from as NodeId].x} ${NODE_POS[edge.from as NodeId].y} L ${NODE_POS[edge.to as NodeId].x} ${NODE_POS[edge.to as NodeId].y}`}
            />
          </circle>
        )}
      </svg>

      {edge && active?.label && (
        <div
          key={`label-${active.key}`}
          data-testid="hop-label"
          className={`absolute z-10 max-w-[46%] -translate-x-1/2 -translate-y-1/2 rounded-full px-2 py-0.5 text-center text-[9px] leading-tight shadow-sm ${
            active.simulation
              ? "bg-amber-100 text-amber-800"
              : "bg-sky-100 text-sky-800"
          }`}
          style={{
            left: `${(NODE_POS[edge.from as NodeId].x + NODE_POS[edge.to as NodeId].x) / 2}%`,
            top: `${(NODE_POS[edge.from as NodeId].y + NODE_POS[edge.to as NodeId].y) / 2}%`,
          }}
        >
          {active.label}
        </div>
      )}

      {NODES.map((n) => {
        const glow = glowing.has(n.id);
        const isAttacker = n.id === "losssink";
        const isLedgerPending = n.id === "ledger" && pending;
        const value = nodeValue(n.id, state);
        return (
          <div
            key={n.id}
            data-testid={`node-${n.id}`}
            data-glow={glow || undefined}
            className={`absolute w-[23%] -translate-x-1/2 -translate-y-1/2 rounded-lg border px-2 py-1.5 text-center transition-shadow ${
              isAttacker
                ? "border-red-300 bg-red-50"
                : glow
                  ? "border-sky-400 bg-sky-50 shadow-[0_0_12px_rgba(56,189,248,0.7)]"
                  : "border-neutral-200 bg-white"
            } ${isLedgerPending ? "animate-pulse border-amber-400 shadow-[0_0_12px_rgba(245,158,11,0.6)]" : ""}`}
            style={{ left: `${n.x}%`, top: `${n.y}%` }}
          >
            <div
              className={`text-[10px] font-semibold ${
                isAttacker ? "text-red-700" : "text-neutral-700"
              }`}
            >
              {n.name}
            </div>
            <div className="text-[8.5px] leading-tight text-neutral-400">
              {n.role}
            </div>
            {n.id === "signer" && state?.random_nonce_signer && (
              <div
                data-testid="signer-random-badge"
                className="mt-0.5 inline-block rounded bg-red-100 px-1 py-px text-[8px] font-semibold text-red-700"
              >
                random nonce
              </div>
            )}
            {value && !(n.id === "signer" && state?.random_nonce_signer) && (
              <div className="mt-0.5 text-[8.5px] font-medium text-neutral-600">
                {value}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
