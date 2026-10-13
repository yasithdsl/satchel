"use client";

import {
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import type { StripNode, Tone } from "@/lib/caption.ts";
import { STRIP_NODES, stripZones } from "@/lib/strip.ts";
import {
  AgentIcon,
  AttackerIcon,
  LaptopIcon,
  LedgerIcon,
  NetworkIcon,
  SignerIcon,
  VaultIcon,
} from "@/components/icons";

export interface StripFocus {
  key: number;
  nodes: StripNode[];
  tone: Tone;
}

const ICONS: Record<StripNode, (p: { className?: string }) => ReactNode> = {
  agent: AgentIcon,
  laptop: LaptopIcon,
  ledger: LedgerIcon,
  vault: VaultIcon,
  signer: SignerIcon,
  network: NetworkIcon,
  attacker: AttackerIcon,
};

const ZONE_STYLE: Record<string, string> = {
  online: "border-line bg-canvas/60",
  you: "border-accent/20 bg-accent-soft/60",
  offline: "border-line bg-canvas/60",
  network: "border-line bg-canvas/60",
};

interface Path {
  key: number;
  x1: number;
  y1: number;
  x2: number;
  y2: number;
  tone: Tone;
}

export function DeviceStrip({
  focus,
  showAttacker,
  randomNonce,
  onNodeClick,
}: {
  focus: StripFocus | null;
  showAttacker: boolean;
  randomNonce: boolean;
  onNodeClick?: (node: StripNode) => void;
}) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const iconRefs = useRef<Partial<Record<StripNode, HTMLSpanElement | null>>>({});
  const dotRef = useRef<HTMLSpanElement | null>(null);
  const [path, setPath] = useState<Path | null>(null);

  const lit = new Set(focus?.nodes ?? []);
  const pulseFrom = focus && focus.nodes.length === 2 ? focus.nodes[0] : null;
  const pulseTo = focus && focus.nodes.length === 2 ? focus.nodes[1] : null;

  useLayoutEffect(() => {
    if (!focus || !pulseFrom || !pulseTo) {
      setPath(null);
      return;
    }
    const box = containerRef.current?.getBoundingClientRect();
    const a = iconRefs.current[pulseFrom]?.getBoundingClientRect();
    const b = iconRefs.current[pulseTo]?.getBoundingClientRect();
    if (!box || !a || !b) {
      setPath(null);
      return;
    }
    setPath({
      key: focus.key,
      x1: a.left + a.width / 2 - box.left,
      y1: a.top + a.height / 2 - box.top,
      x2: b.left + b.width / 2 - box.left,
      y2: b.top + b.height / 2 - box.top,
      tone: focus.tone,
    });
  }, [focus, pulseFrom, pulseTo, showAttacker]);

  useEffect(() => {
    if (!path || !dotRef.current) return;
    const animation = dotRef.current.animate(
      [
        { transform: `translate(${path.x1}px, ${path.y1}px) scale(0.6)`, opacity: 0 },
        { transform: `translate(${path.x1}px, ${path.y1}px) scale(1)`, opacity: 1, offset: 0.12 },
        { transform: `translate(${path.x2}px, ${path.y2}px) scale(1)`, opacity: 1, offset: 0.88 },
        { transform: `translate(${path.x2}px, ${path.y2}px) scale(0.6)`, opacity: 0 },
      ],
      { duration: 1300, easing: "cubic-bezier(0.45, 0, 0.25, 1)", fill: "forwards" },
    );
    return () => animation.cancel();
  }, [path]);

  const pulseColor = path?.tone === "bad" ? "#c42b2b" : path?.tone === "good" ? "#17803d" : "#3451d1";

  return (
    <div
      ref={containerRef}
      data-testid="device-strip"
      className="relative flex h-full flex-col justify-center px-8"
    >
      <div className="relative z-10 flex items-stretch gap-3">
        {stripZones(showAttacker).map((zone) => (
          <div
            key={zone.id}
            data-testid={`zone-${zone.id}`}
            className={`flex min-w-0 flex-col rounded-2xl border px-3 pt-3 pb-3.5 ${ZONE_STYLE[zone.id]}`}
            style={{ flex: zone.nodes.length }}
          >
            <div className="mb-3 text-center text-[13px] font-semibold tracking-[0.18em] text-muted uppercase">
              {zone.label}
            </div>
            <div className="flex flex-1 gap-2.5">
              {zone.nodes.map((id) => {
                const spec = STRIP_NODES[id];
                const Icon = ICONS[id];
                const active = lit.has(id);
                const dim = focus !== null && !active;
                const attacker = id === "attacker";
                const bad = attacker || (active && focus?.tone === "bad");
                const cheating = id === "signer" && randomNonce;
                return (
                  <button
                    key={id}
                    type="button"
                    data-testid={`strip-node-${id}`}
                    data-active={active || undefined}
                    data-dim={dim || undefined}
                    onClick={() => onNodeClick?.(id)}
                    className={`flex min-w-0 flex-1 flex-col items-center rounded-xl border bg-surface px-2 pt-7 pb-6 text-center transition-all duration-500 ${
                      dim ? "opacity-30" : "opacity-100"
                    } ${
                      active
                        ? bad
                          ? "border-bad/50 shadow-[0_0_0_3px_rgb(196_43_43/0.15)]"
                          : "border-accent/50 shadow-[0_0_0_3px_rgb(52_81_209/0.15)]"
                        : attacker
                          ? "border-bad/30"
                          : "border-line"
                    } ${onNodeClick ? "cursor-pointer hover:border-accent/40" : "cursor-default"}`}
                  >
                    <span
                      ref={(el) => {
                        iconRefs.current[id] = el;
                      }}
                      className={`flex h-[clamp(52px,4.1vw,80px)] w-[clamp(52px,4.1vw,80px)] items-center justify-center rounded-full ${
                        attacker || cheating
                          ? "bg-bad-soft text-bad"
                          : active
                            ? "bg-accent text-white"
                            : "bg-accent-soft text-accent"
                      } ${active ? (bad ? "animate-glow-bad" : "animate-glow") : ""}`}
                    >
                      <Icon className="h-[46%] w-[46%]" />
                    </span>
                    <span
                      className={`mt-4 text-[clamp(15px,1.1vw,21px)] leading-tight font-semibold ${
                        attacker ? "text-bad" : "text-ink"
                      }`}
                    >
                      {spec.name}
                    </span>
                    <span
                      data-testid={`strip-line-${id}`}
                      className={`mt-1.5 text-[clamp(12.5px,0.82vw,15.5px)] leading-snug ${
                        cheating || attacker ? "text-bad" : "text-ink-soft"
                      }`}
                    >
                      {cheating ? "Set to cheat (demo)" : spec.line}
                    </span>
                  </button>
                );
              })}
            </div>
          </div>
        ))}
      </div>

      {path && (
        <svg
          key={path.key}
          className="pointer-events-none absolute inset-0 z-20 h-full w-full overflow-visible"
          aria-hidden="true"
        >
          <line
            x1={path.x1}
            y1={path.y1}
            x2={path.x2}
            y2={path.y2}
            stroke={pulseColor}
            strokeOpacity="0.35"
            strokeWidth="3"
            strokeDasharray="2 8"
            strokeLinecap="round"
          />
        </svg>
      )}
      <span
        ref={dotRef}
        data-testid="pulse-dot"
        className="pointer-events-none absolute top-0 left-0 z-30 -mt-2.5 -ml-2.5 h-5 w-5 rounded-full opacity-0 shadow-[0_0_0_6px_rgb(255_255_255/0.85)]"
        style={{ background: pulseColor }}
      />
    </div>
  );
}
