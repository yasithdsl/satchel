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
  SatchelIcon,
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
  compact = false,
  agentSatchel = null,
}: {
  focus: StripFocus | null;
  showAttacker: boolean;
  randomNonce: boolean;
  onNodeClick?: (node: StripNode) => void;
  /** A slim strip above a stage panel. */
  compact?: boolean;
  /** What the agent's satchel holds, shown on the agent node. */
  agentSatchel?: string | null;
}) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const iconRefs = useRef<Partial<Record<StripNode, HTMLSpanElement | null>>>({});
  const dotRef = useRef<HTMLSpanElement | null>(null);
  const [path, setPath] = useState<Path | null>(null);
  // The slim strip puts each icon beside its name, or above it when a name wouldn't fit.
  const [stacked, setStacked] = useState(false);
  const [width, setWidth] = useState(0);

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

  useLayoutEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const observer = new ResizeObserver(([entry]) => setWidth(Math.round(entry.contentRect.width)));
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  // Try side by side again whenever the room or the content changes...
  useLayoutEffect(() => {
    setStacked(false);
  }, [compact, width, showAttacker, randomNonce, agentSatchel]);

  // ...and stack before painting if any name or line would be cut.
  useLayoutEffect(() => {
    if (!compact || stacked) return;
    const cut = [...(containerRef.current?.querySelectorAll<HTMLElement>("[data-fit]") ?? [])].some(
      (el) => el.scrollWidth > el.clientWidth + 1,
    );
    if (cut) setStacked(true);
  });

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
      className={`relative flex flex-col justify-center px-8 ${compact ? "shrink-0 py-3" : "h-full"}`}
    >
      <div className={`flex items-stretch ${compact ? "gap-2" : "gap-3"}`}>
        {stripZones(showAttacker).map((zone) => (
          <div
            key={zone.id}
            data-testid={`zone-${zone.id}`}
            className={`flex min-w-0 flex-col rounded-2xl border ${compact ? "px-2 pt-1.5 pb-2" : "px-3 pt-3 pb-3.5"} ${ZONE_STYLE[zone.id]}`}
            style={{ flex: zone.nodes.length }}
          >
            <div
              className={`text-center font-semibold tracking-[0.18em] text-muted uppercase ${
                compact ? "mb-1 text-[11px]" : "mb-3 text-[13px]"
              }`}
            >
              {zone.label}
            </div>
            <div className={`flex flex-1 ${compact ? "gap-1.5" : "gap-2.5"}`}>
              {zone.nodes.map((id) => {
                const spec = STRIP_NODES[id];
                const Icon = ICONS[id];
                const active = lit.has(id);
                const dim = focus !== null && !active;
                const attacker = id === "attacker";
                const bad = attacker || (active && focus?.tone === "bad");
                const cheating = id === "signer" && randomNonce;
                const icon = (
                  <span
                    ref={(el) => {
                      iconRefs.current[id] = el;
                    }}
                    className={`flex shrink-0 items-center justify-center rounded-full ${
                      compact
                        ? "h-[clamp(32px,2.4vw,44px)] w-[clamp(32px,2.4vw,44px)]"
                        : "h-[clamp(52px,4.1vw,80px)] w-[clamp(52px,4.1vw,80px)]"
                    } ${
                      attacker || cheating
                        ? "bg-bad-soft text-bad"
                        : active
                          ? "bg-accent text-white"
                          : "bg-accent-soft text-accent"
                    } ${active ? (bad ? "animate-glow-bad" : "animate-glow") : ""}`}
                  >
                    <Icon className="h-[46%] w-[46%]" />
                  </span>
                );
                const badge = id === "agent" && agentSatchel && (
                  <span
                    data-testid="agent-satchel"
                    className={`flex w-fit shrink-0 items-center gap-1 rounded-full bg-good-soft font-semibold whitespace-nowrap text-good ${
                      compact ? "mt-0.5 px-1.5 py-px text-[12px]" : "mt-2 px-2.5 py-1 text-[13px]"
                    }`}
                  >
                    <SatchelIcon className={compact ? "h-3 w-3" : "h-4 w-4"} />
                    {agentSatchel}
                  </span>
                );
                const lineText = cheating ? (compact ? "Rigged (demo)" : "Set to cheat (demo)") : spec.line;
                const nameColor = attacker ? "text-bad" : "text-ink";
                const lineColor = cheating || attacker ? "text-bad" : "text-ink-soft";
                return (
                  <button
                    key={id}
                    type="button"
                    data-testid={`strip-node-${id}`}
                    data-active={active || undefined}
                    data-dim={dim || undefined}
                    onClick={() => onNodeClick?.(id)}
                    className={`relative z-20 flex min-w-0 flex-1 items-center rounded-xl border bg-surface transition-all duration-500 *:transition-opacity *:duration-500 ${
                      compact ? (stacked ? "justify-center px-1.5 py-2" : "px-2 py-2") : "flex-col px-2 pt-7 pb-6 text-center"
                    } ${
                      dim ? "*:opacity-30" : ""
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
                    {compact ? (
                      <span
                        className={`flex min-w-0 max-w-full items-center ${
                          stacked ? "flex-col gap-1 text-center" : "w-full gap-2 text-left"
                        }`}
                      >
                        {icon}
                        <span className={`flex min-w-0 max-w-full flex-col ${stacked ? "items-center" : "items-start"}`}>
                          <span
                            data-fit
                            className={`block max-w-full truncate leading-tight font-semibold ${
                              stacked ? "text-[13px]" : "text-[clamp(13px,0.9vw,16px)]"
                            } ${nameColor}`}
                          >
                            {spec.short ?? spec.name}
                          </span>
                          {badge ||
                            ((cheating || attacker) && (
                              <span
                                data-fit
                                data-testid={`strip-line-${id}`}
                                className={`block max-w-full truncate leading-snug ${
                                  stacked ? "text-[11px]" : "text-[12px]"
                                } ${lineColor}`}
                              >
                                {lineText}
                              </span>
                            ))}
                        </span>
                      </span>
                    ) : (
                      <>
                        {icon}
                        <span
                          className={`mt-4 block text-[clamp(15px,1.1vw,21px)] leading-tight font-semibold ${nameColor}`}
                        >
                          {spec.name}
                        </span>
                        <span
                          data-testid={`strip-line-${id}`}
                          className={`mt-1.5 block text-[clamp(12.5px,0.82vw,15.5px)] leading-snug ${lineColor}`}
                        >
                          {lineText}
                        </span>
                        {badge}
                      </>
                    )}
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
          className="pointer-events-none absolute inset-0 z-10 h-full w-full overflow-visible"
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
        data-layout-free
        className="pointer-events-none absolute top-0 left-0 z-30 -mt-2.5 -ml-2.5 h-5 w-5 rounded-full opacity-0 shadow-[0_0_0_6px_rgb(255_255_255/0.85)]"
        style={{ background: pulseColor }}
      />
    </div>
  );
}
