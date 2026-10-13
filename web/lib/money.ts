/** Fixed demo rate from the catalogue: $100,000 per BTC, so 1,000 sats is $1. */
export const SATS_PER_USD = 1_000;

export function usdFromDollars(dollars: number): string {
  if (dollars > 0 && dollars < 0.5) return "<$1";
  return `$${Math.round(dollars).toLocaleString("en-US")}`;
}

/** Whole US dollars at the demo rate, the way every balance is shown. */
export function usd(sats: number): string {
  return usdFromDollars(sats / SATS_PER_USD);
}

/** Small secondary BTC text, for example "0.00179 BTC". */
export function btc(sats: number): string {
  const fixed = (sats / 100_000_000).toFixed(8);
  return `${fixed.replace(/0+$/, "").replace(/\.$/, "")} BTC`;
}

export function btcTextToSats(text: string): number | null {
  const match = /^(\d+)(?:\.(\d{1,8}))?$/.exec(text.trim());
  if (!match) return null;
  const whole = Number(match[1]);
  const frac = Number((match[2] ?? "").padEnd(8, "0"));
  return whole * 100_000_000 + frac;
}
