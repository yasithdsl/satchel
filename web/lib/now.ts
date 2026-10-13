import { storyLine } from "./story.ts";
import type { XrayEvent } from "./xray.ts";

export type BannerTone = "amber" | "red" | "neutral";

export interface Banner {
  tone: BannerTone;
  text: string;
}

const VAULT_BLOCK_WINDOW_MS = 60_000;

export interface NowInput {
  pendingText: string | null;
  events: XrayEvent[];
  now?: number;
}

export function nowBanner(input: NowInput): Banner {
  const { pendingText, events } = input;
  const now = input.now ?? Date.now();

  if (pendingText) {
    return {
      tone: "amber",
      text: `Approval needed on your Ledger: “${pendingText}”`,
    };
  }

  for (let i = events.length - 1; i >= 0; i--) {
    const e = events[i];
    if (!e.alert) continue;
    const age = now - Date.parse(e.ts);
    if (Number.isFinite(age) && age >= 0 && age < VAULT_BLOCK_WINDOW_MS) {
      const reason = e.alert.reasons?.[0];
      return {
        tone: "red",
        text: reason ? `${e.alert.title}: ${reason}` : e.alert.title,
      };
    }
    break;
  }

  let lastStarted = -1;
  let lastFinished = -1;
  for (let i = events.length - 1; i >= 0; i--) {
    const t = events[i].type;
    if (lastFinished === -1 && t === "compromise_finished") {
      lastFinished = i;
    }
    if (t === "compromise_started") {
      lastStarted = i;
      break;
    }
  }
  if (lastStarted !== -1 && lastStarted > lastFinished) {
    const line = storyLine(events[lastStarted]);
    return {
      tone: "amber",
      text: line?.text ?? "SIMULATION running",
    };
  }

  for (let i = events.length - 1; i >= 0; i--) {
    const line = storyLine(events[i]);
    if (line) return { tone: "neutral", text: line.text };
  }

  return { tone: "neutral", text: "Waiting for the shopper" };
}
