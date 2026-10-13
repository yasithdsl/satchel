import { readSse } from "./sse.ts";
import { XRAY_URL } from "./api.ts";
import type { XrayEvent } from "./xray.ts";

const MAX_EVENTS = 2000;
const BACKLOG = 500;
const BASE_BACKOFF_MS = 500;
const MAX_BACKOFF_MS = 5000;

export class EventStore {
  private events = new Map<number, XrayEvent>();
  private listeners = new Set<() => void>();
  private bootId: string | null = null;
  private lastId = 0;
  private controller: AbortController | null = null;
  private cached: XrayEvent[] = [];
  private notifyTimer: ReturnType<typeof setTimeout> | null = null;

  get snapshot(): XrayEvent[] {
    return this.cached;
  }

  get size(): number {
    return this.events.size;
  }

  get lastSeq(): number {
    return this.lastId;
  }

  get running(): boolean {
    return this.controller !== null;
  }

  subscribe = (fn: () => void): (() => void) => {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  };

  ingest(event: XrayEvent): void {
    if (event.boot && this.bootId !== null && event.boot !== this.bootId) {
      this.events.clear();
    }
    if (event.boot) {
      this.bootId = event.boot;
    }
    if (typeof event.seq === "number") {
      if (event.seq > this.lastId) this.lastId = event.seq;
      this.events.set(event.seq, event);
    } else {
      this.events.set(++this.lastId, event);
    }
    while (this.events.size > MAX_EVENTS) {
      const first = this.events.keys().next().value;
      if (first === undefined) break;
      this.events.delete(first);
    }
    this.cached = [...this.events.values()].sort(
      (a, b) => a.seq - b.seq,
    );
    this.scheduleNotify();
  }

  /** One notification per burst: a 500-event backlog re-renders once, not 500 times. */
  private scheduleNotify(): void {
    if (this.notifyTimer) return;
    this.notifyTimer = setTimeout(() => {
      this.notifyTimer = null;
      for (const fn of this.listeners) fn();
    }, 0);
  }

  reset(): void {
    this.events.clear();
    this.cached = [];
    this.scheduleNotify();
    this.bootId = null;
    this.lastId = 0;
  }

  start(): void {
    if (this.controller) return;
    const controller = new AbortController();
    this.controller = controller;
    void this.loop(controller.signal).finally(() => {
      if (this.controller === controller) this.controller = null;
    });
  }

  stop(): void {
    this.controller?.abort();
    this.controller = null;
  }

  private async loop(signal: AbortSignal): Promise<void> {
    let backoff = BASE_BACKOFF_MS;
    while (!signal.aborted) {
      try {
        const headers: Record<string, string> = {};
        if (this.lastId > 0) {
          headers["Last-Event-ID"] = String(this.lastId);
        }
        const response = await fetch(
          `${XRAY_URL}/events?backlog=${BACKLOG}`,
          { headers, signal },
        );
        if (!response.ok) {
          throw new Error(`events ${response.status}`);
        }
        backoff = BASE_BACKOFF_MS;
        for await (const msg of readSse(response)) {
          const event = JSON.parse(msg.data) as XrayEvent;
          this.ingest(event);
        }
      } catch (err) {
        if (signal.aborted) return;
      }
      await sleep(backoff);
      backoff = Math.min(backoff * 2, MAX_BACKOFF_MS);
    }
  }
}

export const xrayStore = new EventStore();

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
