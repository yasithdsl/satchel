import type { MomentKind, StoryContext } from "./caption.ts";
import type { XrayEvent } from "./xray.ts";
import { usd } from "./money.ts";

export interface Moment {
  kind: MomentKind;
  tone: "good" | "bad";
  /** The full-width banner sentence. */
  text: string;
  /** What the banner shrinks to once its moment has passed. */
  badge: string;
}

function num(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

/** The banner for a scene's one big moment, with the numbers it promises. */
export function momentFor(
  kind: MomentKind,
  event: XrayEvent,
  ctx: StoryContext,
  mainFundsSats: number | null,
): Moment {
  const p = event.payload ?? {};
  switch (kind) {
    case "purchase": {
      const index = num(p.envelope_index);
      const budget = index !== null ? ctx.budgetByEnvelope[index] : undefined;
      return {
        kind,
        tone: "good",
        text: `Paid from the ${budget !== undefined ? `${usd(budget)} ` : ""}satchel. No Ledger tap needed.`,
        badge: "Paid from the satchel",
      };
    }
    case "compromise": {
      const before = num(p.envelope_balance_before);
      const budget = ctx.attack.budgetSats;
      const lost =
        before === null
          ? "It lost its satchel."
          : budget !== null && before < budget
            ? `It lost the ${usd(before)} left in its satchel.`
            : `It lost its ${usd(budget ?? before)} satchel.`;
      const main =
        mainFundsSats !== null
          ? ` Main funds untouched: ${usd(mainFundsSats)}.`
          : " Main funds untouched.";
      return {
        kind,
        tone: "bad",
        text: `Simulated attack: the agent is fully compromised. ${lost}${main}`,
        badge: "Simulated attack",
      };
    }
    case "blocked":
      return {
        kind,
        tone: "bad",
        text: "Vault blocked the transaction: the signer's signature didn't match. Nothing was sent.",
        badge: "Vault blocked it",
      };
  }
}
