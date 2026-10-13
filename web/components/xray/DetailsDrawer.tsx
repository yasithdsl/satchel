"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import QRCode from "qrcode";
import { captionAll, type StripNode } from "@/lib/caption.ts";
import { payloadEvents, payloadName } from "@/lib/payloads.ts";
import { nextIndex, partAt } from "@/lib/qr.ts";
import { STRIP_NODES } from "@/lib/strip.ts";

const NODE_TABS: StripNode[] = ["agent", "laptop", "ledger", "vault", "signer", "network"];
import { feedTime, type XrayEvent } from "@/lib/xray.ts";

const PART_MS = 600;
const LOG_LIMIT = 150;

export interface DetailsSelection {
  /** Opened from a device: show that device's latest payload. */
  node: StripNode | null;
  payload: XrayEvent | null;
}

function QrView({ event }: { event: XrayEvent }) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const parts = useMemo(() => event.qr?.parts ?? [], [event]);
  const [index, setIndex] = useState(0);

  useEffect(() => setIndex(0), [event.id]);

  useEffect(() => {
    if (parts.length <= 1) return;
    const timer = setInterval(() => setIndex((i) => nextIndex(parts, i)), PART_MS);
    return () => clearInterval(timer);
  }, [parts]);

  useEffect(() => {
    const part = partAt(parts, index);
    if (!part || !canvasRef.current) return;
    void QRCode.toCanvas(canvasRef.current, part, {
      width: 220,
      margin: 1,
      errorCorrectionLevel: "L",
    });
  }, [parts, index]);

  return (
    <div className="flex flex-col items-start gap-3">
      <canvas
        ref={canvasRef}
        data-testid="qr-canvas"
        className="h-[200px] w-[200px] rounded-lg border border-line bg-white"
      />
      <p data-testid="qr-label" className="text-[16px] leading-snug text-ink">
        {event.label}
      </p>
      <div className="flex flex-wrap items-center gap-1.5 text-[12px]">
        <span className="rounded-full bg-canvas px-2 py-0.5 text-ink-soft">
          {payloadName(event.qr?.type)}
        </span>
        {event.qr?.redacted && (
          <span className="rounded-full bg-accent-soft px-2 py-0.5 font-medium text-accent-ink">
            keys hidden
          </span>
        )}
        {parts.length > 1 && (
          <span className="text-muted">
            part {index + 1} of {parts.length}
          </span>
        )}
      </div>
    </div>
  );
}

export function DetailsDrawer({
  events,
  open,
  selection,
  onSelect,
  onNode,
}: {
  events: XrayEvent[];
  open: boolean;
  selection: DetailsSelection;
  onSelect: (payload: XrayEvent) => void;
  onNode: (node: StripNode) => void;
}) {
  const payloads = useMemo(() => payloadEvents(events).slice(0, 8), [events]);
  const log = useMemo(
    () => captionAll(events).items.slice(-LOG_LIMIT).reverse(),
    [events],
  );
  const shown = selection.payload ?? (selection.node ? null : payloads[0] ?? null);

  if (!open) return null;
  return (
    <>
      {open && (
        <div
          data-testid="details-drawer"
          className="animate-rise absolute inset-x-0 bottom-[52px] z-30 flex h-[62%] gap-8 border-t border-line bg-surface px-10 py-6 shadow-[0_-18px_40px_-24px_rgb(0_0_0/0.25)]"
        >
          <section className="flex w-[300px] shrink-0 flex-col">
            <div className="mb-3 flex flex-wrap gap-1">
              {NODE_TABS.map((node) => (
                <button
                  key={node}
                  type="button"
                  data-testid={`details-node-${node}`}
                  onClick={() => onNode(node)}
                  className={`rounded-full px-2.5 py-0.5 text-[12px] transition ${
                    selection.node === node
                      ? "bg-accent text-white"
                      : "bg-canvas text-ink-soft hover:text-ink"
                  }`}
                >
                  {node === "network" ? "Network" : STRIP_NODES[node].name}
                </button>
              ))}
            </div>
            <h3 className="mb-3 text-[12px] font-semibold tracking-[0.16em] text-muted uppercase">
              {selection.node
                ? `${STRIP_NODES[selection.node].name}: latest payload`
                : "Latest payload"}
            </h3>
            {shown ? (
              <QrView event={shown} />
            ) : (
              <p className="text-[15px] text-ink-soft">
                {selection.node
                  ? `Nothing has crossed into or out of the ${STRIP_NODES[selection.node].name.toLowerCase()} yet.`
                  : "Payloads appear here as QR codes once devices exchange them."}
              </p>
            )}
            {payloads.length > 1 && (
              <div className="mt-4 min-h-0 space-y-0.5 overflow-y-auto border-t border-line pt-3">
                {payloads.map((p) => (
                  <button
                    key={p.id}
                    type="button"
                    onClick={() => onSelect(p)}
                    className={`block w-full truncate rounded-md px-2 py-1 text-left text-[13px] transition ${
                      p.id === shown?.id
                        ? "bg-accent-soft text-accent-ink"
                        : "text-ink-soft hover:bg-canvas"
                    }`}
                  >
                    {p.label}
                  </button>
                ))}
              </div>
            )}
          </section>
          <section className="flex min-w-0 flex-1 flex-col">
            <h3 className="mb-3 text-[12px] font-semibold tracking-[0.16em] text-muted uppercase">
              Event log
            </h3>
            <ol data-testid="event-log" className="min-h-0 space-y-1.5 overflow-y-auto pr-2">
              {log.length === 0 && (
                <li className="text-[15px] text-ink-soft">Nothing has happened yet.</li>
              )}
              {log.map(({ event, caption }) => (
                <li key={event.seq} className="flex gap-3 text-[14px] leading-snug">
                  <span className="w-[70px] shrink-0 font-mono text-[12px] leading-[1.6] text-muted tabular-nums">
                    {feedTime(event.ts)}
                  </span>
                  <span
                    className={`mt-[7px] h-1.5 w-1.5 shrink-0 rounded-full ${
                      caption.tone === "bad"
                        ? "bg-bad"
                        : caption.tone === "good"
                          ? "bg-good"
                          : "bg-accent"
                    }`}
                  />
                  <span className={caption.tone === "bad" ? "text-bad" : "text-ink"}>
                    {caption.text}
                  </span>
                </li>
              ))}
            </ol>
          </section>
        </div>
      )}
    </>
  );
}
