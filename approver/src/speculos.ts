/** DEMO ONLY: drives the Speculos HTTP API to approve or reject the review on screen. */

const SPECULOS_URL = process.env.SPECULOS_URL ?? "http://127.0.0.1:5001";
const HOLD_MS = 4_000;
const POLL_MS = 300;
const MAX_PAGES = 20;
const PAGE_SETTLE_MS = 500;

type ScreenEvent = {
  text: string;
  x: number;
  y: number;
  w: number;
  h: number;
};

export class SpeculosDriver {
  private readonly base: string;

  constructor(base: string = SPECULOS_URL) {
    this.base = base.replace(/\/$/, "");
  }

  async screen(): Promise<ScreenEvent[]> {
    const res = await fetch(`${this.base}/events?currentscreenonly=true`);
    if (!res.ok) throw new Error(`speculos /events ${res.status}`);
    const body = (await res.json()) as { events?: ScreenEvent[] };
    return body.events ?? [];
  }

  async texts(): Promise<string[]> {
    return (await this.screen()).map((e) => e.text);
  }

  async screenshot(): Promise<Uint8Array> {
    const res = await fetch(`${this.base}/screenshot`);
    if (!res.ok) throw new Error(`speculos /screenshot ${res.status}`);
    return new Uint8Array(await res.arrayBuffer());
  }

  async tap(x: number, y: number): Promise<void> {
    await this.finger({ action: "press-and-release", x, y });
  }

  async tapEvent(event: ScreenEvent): Promise<void> {
    await this.tap(Math.round(event.x + event.w / 2), Math.round(event.y + event.h / 2));
  }

  private async finger(body: Record<string, unknown>): Promise<void> {
    const res = await fetch(`${this.base}/finger`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error(`speculos /finger ${res.status}`);
  }

  private async swipeBack(): Promise<void> {
    await this.finger({
      action: "press-and-release",
      x: 400,
      y: 300,
      x2: 80,
      y2: 300,
      delay: 0.4,
    });
    await sleep(PAGE_SETTLE_MS);
  }

  private async hold(x: number, y: number, ms: number): Promise<void> {
    await this.finger({ action: "press", x, y });
    await sleep(ms);
    await this.finger({ action: "release", x, y });
  }

  private findEvent(events: ScreenEvent[], needle: string): ScreenEvent | undefined {
    return events.find((e) => e.text === needle || e.text.startsWith(needle));
  }

  /** Page through the review and hold the final sign control. */
  async approveReview(): Promise<void> {
    for (let page = 0; page < MAX_PAGES; page++) {
      const events = await this.screen();
      const hold = events.find((e) => e.text.startsWith("Hold to "));
      if (hold) {
        await this.hold(
          Math.round(hold.x + hold.w / 2),
          Math.round(hold.y + hold.h / 2),
          HOLD_MS,
        );
        await sleep(PAGE_SETTLE_MS);
        return;
      }
      if (events.length === 0) {
        await sleep(POLL_MS);
        continue;
      }
      await this.swipeBack();
    }
    throw new Error("never found the hold-to-sign control");
  }

  /** Tap the reject control, then confirm. */
  async rejectReview(): Promise<void> {
    for (let page = 0; page < MAX_PAGES; page++) {
      const events = await this.screen();
      const confirm = this.findEvent(events, "Yes, reject");
      if (confirm) {
        await this.tapEvent(confirm);
        return;
      }
      const reject = this.findEvent(events, "Reject");
      if (reject) {
        await this.tapEvent(reject);
        await sleep(PAGE_SETTLE_MS);
        continue;
      }
      if (events.length === 0) {
        await sleep(POLL_MS);
        continue;
      }
      await this.swipeBack();
    }
    throw new Error("never found the reject control");
  }
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
