"use client";

import type { StoryContext } from "@/lib/caption.ts";
import { CheckIcon, KeyIcon, SignerIcon, VaultIcon, XIcon } from "@/components/icons";

/** A stylised signature: the same bytes every time for the honest one. */
const HONEST = [7, 3, 9, 4, 8, 2, 6, 5, 9, 3, 7, 4, 6, 8, 2, 5];
const FORGED = [7, 8, 2, 9, 3, 7, 4, 9, 1, 6, 2, 8, 9, 3, 6, 1];

function Signature({ bars, tone, label }: { bars: number[]; tone: "good" | "bad" | "muted"; label: string }) {
  const color = tone === "good" ? "bg-good" : tone === "bad" ? "bg-bad" : "bg-line";
  return (
    <div>
      <div className="mb-1 text-[13px] text-ink-soft">{label}</div>
      <div className="flex h-10 items-end gap-[3px]">
        {bars.map((h, i) => (
          <span key={i} className={`w-full rounded-sm ${color}`} style={{ height: `${h * 10}%` }} />
        ))}
      </div>
    </div>
  );
}

export function SignerPanel({ ctx }: { ctx: StoryContext }) {
  const verdict = ctx.signer.verdict;
  const signed = verdict !== null;
  return (
    <div data-testid="signer-panel" className="grid grid-cols-3 gap-5 px-10 py-4">
      <section className="flex flex-col rounded-2xl border-2 border-bad/30 bg-bad-soft/40 p-5 short:p-4">
        <div className="flex items-center gap-2 text-[13px] font-semibold tracking-[0.14em] text-bad uppercase">
          <SignerIcon className="h-5 w-5" /> The threat
        </div>
        <div className="mt-3 text-[20px] leading-snug font-semibold text-ink">
          A rigged signer (Dark Skippy)
        </div>
        <p className="mt-2 text-[15px] leading-relaxed text-ink-soft">
          Every signature needs a secret random number. A malicious device can pick numbers that
          quietly encode your seed, and leak the whole wallet in a couple of signatures.
        </p>
      </section>

      <section className="flex flex-col rounded-2xl border border-line bg-surface p-5 short:p-4">
        <div className="flex items-center gap-2 text-[13px] font-semibold tracking-[0.14em] text-accent uppercase">
          <KeyIcon className="h-5 w-5" /> Defence 1
        </div>
        <div className="mt-3 text-[20px] leading-snug font-semibold text-ink">
          It never holds the seed
        </div>
        <p className="mt-2 text-[15px] leading-relaxed text-ink-soft">
          The signer only gets one-time child keys for this payment. They are fully hardened, so
          even a leaked key can&apos;t reach any other.
        </p>
      </section>

      <section
        data-testid="signature-check"
        data-verdict={verdict ?? "none"}
        className={`flex flex-col rounded-2xl border p-5 transition-colors short:p-4 ${
          verdict === "forged"
            ? "border-bad/50 bg-surface"
            : verdict === "honest"
              ? "border-good/40 bg-surface"
              : "border-line bg-surface"
        }`}
      >
        <div className="flex items-center gap-2 text-[13px] font-semibold tracking-[0.14em] text-accent uppercase">
          <VaultIcon className="h-5 w-5" /> Defence 2
        </div>
        <div className="mt-3 text-[20px] leading-snug font-semibold text-ink">
          The vault checks every byte
        </div>
        <div className="mt-3 space-y-2">
          <Signature bars={HONEST} tone="good" label="Honest signature (RFC 6979), recomputed by the vault" />
          <Signature
            bars={verdict === "forged" ? FORGED : HONEST}
            tone={!signed ? "muted" : verdict === "forged" ? "bad" : verdict === "honest" ? "good" : "muted"}
            label="The signer's signature"
          />
        </div>
        <div className="mt-3 flex items-center gap-2 text-[15px] font-medium">
          {verdict === "forged" ? (
            <span className="flex items-center gap-1.5 text-bad">
              <XIcon className="h-5 w-5" /> Doesn&apos;t match: blocked, nothing sent
            </span>
          ) : verdict === "honest" ? (
            <span className="flex items-center gap-1.5 text-good">
              <CheckIcon className="h-5 w-5" /> Matches: safe to send
            </span>
          ) : (
            <span className="text-muted">Waiting for a signature…</span>
          )}
        </div>
      </section>
    </div>
  );
}
