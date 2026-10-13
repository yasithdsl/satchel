/** DEMO ONLY: drives the Speculos HTTP API to approve or reject the review on screen. */

const SPECULOS_URL = process.env.SPECULOS_URL ?? "http://127.0.0.1:5001";
const HOLD_MS = 4_000;
const POLL_MS = 300;
const MAX_PAGES = 20;
const PAGE_SETTLE_MS = 500;
const REVIEW_WAIT_MS = 20_000;

/** The review was decided (or withdrawn) while the automation was running. */
export class ReviewGone extends Error {
  constructor() {
    super("nothing is waiting for approval on the device");
    this.name = "ReviewGone";
  }
}

export type ReviewOptions = {
  /** Checked before every step; false once the request was decided. */
  stillPending?: () => boolean;
  reviewWaitMs?: number;
};

const HOME_RE = /^(quit app|this app enables signing)/i;

/** The app's idle screen: no review to page through yet (or any more). */
export function isHomeScreen(events: { text: string }[]): boolean {
  return events.some((e) => HOME_RE.test(e.text.trim()));
}

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

  /** Wait out an empty or home screen; the review may still be on its way. */
  private async reviewScreen(
    options: ReviewOptions,
    deadline: number,
  ): Promise<ScreenEvent[]> {
    while (true) {
      if (options.stillPending && !options.stillPending()) {
        throw new ReviewGone();
      }
      const events = await this.screen();
      if (events.length > 0 && !isHomeScreen(events)) return events;
      if (Date.now() > deadline) {
        throw new Error("the review never reached the device");
      }
      await sleep(POLL_MS);
    }
  }

  /** Page through the review and hold the final sign control. */
  async approveReview(options: ReviewOptions = {}): Promise<void> {
    const deadline = Date.now() + (options.reviewWaitMs ?? REVIEW_WAIT_MS);
    for (let page = 0; page < MAX_PAGES; page++) {
      const events = await this.reviewScreen(options, deadline);
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
      await this.swipeBack();
    }
    throw new Error("never found the hold-to-sign control");
  }

  /** Tap the reject control, then confirm. */
  async rejectReview(options: ReviewOptions = {}): Promise<void> {
    const deadline = Date.now() + (options.reviewWaitMs ?? REVIEW_WAIT_MS);
    for (let page = 0; page < MAX_PAGES; page++) {
      const events = await this.reviewScreen(options, deadline);
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
      await this.swipeBack();
    }
    throw new Error("never found the reject control");
  }
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
