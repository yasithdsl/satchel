import { getState, type XrayState } from "./api.ts";
import { mergeState } from "./state.ts";

const POLL_MS = 2_000;
const DEBOUNCE_MS = 250;

/** One shared /state snapshot, so every balance on screen reads the same numbers. */
export class StateStore {
  private state: XrayState | null = null;
  private listeners = new Set<() => void>();
  private timer: ReturnType<typeof setInterval> | null = null;
  private pending: ReturnType<typeof setTimeout> | null = null;
  private inFlight = false;

  constructor(private readonly fetcher: () => Promise<XrayState> = getState) {}

  get snapshot(): XrayState | null {
    return this.state;
  }

  subscribe = (fn: () => void): (() => void) => {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  };

  set(next: XrayState): void {
    this.state = mergeState(this.state, next);
    for (const fn of this.listeners) fn();
  }

  clear(): void {
    this.state = null;
    for (const fn of this.listeners) fn();
  }

  start(intervalMs = POLL_MS): void {
    if (this.timer) return;
    void this.load();
    this.timer = setInterval(() => void this.load(), intervalMs);
  }

  stop(): void {
    if (this.timer) clearInterval(this.timer);
    if (this.pending) clearTimeout(this.pending);
    this.timer = null;
    this.pending = null;
  }

  /** Refresh soon after something happened, coalescing bursts of events. */
  refreshSoon(): void {
    if (this.pending) return;
    this.pending = setTimeout(() => {
      this.pending = null;
      void this.load();
    }, DEBOUNCE_MS);
  }

  async load(): Promise<void> {
    if (this.inFlight) return;
    this.inFlight = true;
    try {
      this.set(await this.fetcher());
    } catch (err) {
      console.debug("x-ray state unavailable", err);
    } finally {
      this.inFlight = false;
    }
  }
}

export const stateStore = new StateStore();
