"use client";

import { useCallback, useEffect, useRef, useState, type RefObject } from "react";
import type { ChatControls } from "@/components/Chat";
import {
  mineBlock,
  resetDemo,
  runCompromise,
  setRandomNonce,
  xrayBootId,
  type XrayState,
} from "@/lib/api.ts";
import { retryWhileBusy } from "@/lib/retry.ts";
import { ATTACK_REQUEST_SATS, SCENES } from "@/lib/scenes.ts";
import { stateStore } from "@/lib/stateStore.ts";
import { xrayStore } from "@/lib/store.ts";

const CONFIRM_MS = 4_000;
const RESET_POLL_MS = 2_000;
const RESET_GIVE_UP_MS = 5 * 60_000;

type ResetPhase = "idle" | "confirm" | "running";

function isTyping(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null;
  if (!el) return false;
  return (
    el.tagName === "INPUT" ||
    el.tagName === "TEXTAREA" ||
    el.tagName === "SELECT" ||
    el.isContentEditable
  );
}

function Button({
  children,
  onClick,
  disabled,
  tone = "plain",
  testId,
}: {
  children: React.ReactNode;
  onClick: () => void;
  disabled?: boolean;
  tone?: "plain" | "primary" | "danger";
  testId?: string;
}) {
  const tones = {
    plain: "border-white/15 bg-white/5 hover:bg-white/10",
    primary: "border-transparent bg-accent hover:bg-accent-ink",
    danger: "border-[#c42b2b]/60 bg-[#c42b2b]/15 hover:bg-[#c42b2b]/25",
  };
  return (
    <button
      type="button"
      data-testid={testId}
      onClick={onClick}
      disabled={disabled}
      className={`rounded-xl border px-3 py-2 text-left text-[14px] font-medium text-white transition disabled:opacity-35 ${tones[tone]}`}
    >
      {children}
    </button>
  );
}

export default function Presenter({
  controls,
  sessionId,
  chatBusy,
  state,
}: {
  controls: RefObject<ChatControls | null>;
  sessionId: string | null;
  /** The agent's turn holds the session; the attack waits for it to finish. */
  chatBusy: boolean;
  state: XrayState | null;
}) {
  const [open, setOpen] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [reset, setReset] = useState<ResetPhase>("idle");
  const confirmTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.metaKey || e.ctrlKey || e.altKey || isTyping(e.target)) return;
      if (e.key === "p" || e.key === "P") {
        e.preventDefault();
        setOpen((v) => !v);
      } else if (e.key === "Escape") {
        setOpen(false);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const run = useCallback(
    async (id: string, action: () => Promise<unknown>, done: string) => {
      setBusy(id);
      setNote(null);
      try {
        await action();
        setNote(done);
      } catch (err) {
        console.warn(`[satchel] presenter ${id}:`, err);
        setNote("That didn't work. Try again.");
      } finally {
        setBusy(null);
        void stateStore.load();
      }
    },
    [],
  );

  const startScene = (message: string) => {
    controls.current?.newChat();
    controls.current?.send(message);
    setNote("Sent in a new chat.");
  };

  const followUp = (message: string) => {
    controls.current?.send(message);
    setNote("Sent.");
  };

  const randomNonce = state?.random_nonce_signer === true;

  const onReset = async () => {
    if (reset === "idle") {
      setReset("confirm");
      confirmTimer.current = setTimeout(() => setReset("idle"), CONFIRM_MS);
      return;
    }
    if (reset !== "confirm") return;
    if (confirmTimer.current) clearTimeout(confirmTimer.current);
    const before = await xrayBootId();
    const result = await resetDemo();
    if (result === "disabled") {
      setReset("idle");
      setNote("Reset runs from the terminal here: uv run scripts/demo_reset.py");
      return;
    }
    if (result === "error") {
      setReset("idle");
      setNote("That didn't work. Try again.");
      return;
    }
    setReset("running");
    // Every service restarts; stop polling them until the page reloads.
    xrayStore.stop();
    stateStore.stop();
    const started = Date.now();
    let wentDown = false;
    while (Date.now() - started < RESET_GIVE_UP_MS) {
      await new Promise((r) => setTimeout(r, RESET_POLL_MS));
      const boot = await xrayBootId();
      if (boot === null) wentDown = true;
      if (boot !== null && (wentDown || boot !== before)) {
        window.location.reload();
        return;
      }
    }
    setReset("idle");
    setNote("The reset is taking too long. Check .satchel/reset.log.");
  };

  return (
    <>
      {reset === "running" && (
        <div
          data-testid="reset-overlay"
          className="fixed inset-0 z-[60] flex flex-col items-center justify-center gap-3 bg-canvas/95 text-center"
        >
          <div className="text-[30px] font-semibold text-ink">Resetting the demo…</div>
          <div className="text-[18px] text-ink-soft">
            A fresh chain, a fresh vault and fresh budgets. This takes about a minute.
          </div>
        </div>
      )}
      {open && (
        <div
          data-testid="presenter-drawer"
          className="animate-rise fixed bottom-4 left-4 z-50 max-h-[calc(100vh-2rem)] w-[420px] overflow-y-auto rounded-2xl bg-[#17171a] p-5 text-white shadow-[0_24px_60px_-12px_rgb(0_0_0/0.5)]"
        >
          <div className="mb-4 flex items-center justify-between">
            <span className="text-[15px] font-semibold">Presenter</span>
            <span className="text-[12px] text-white/50">P to hide</span>
          </div>

          <div className="space-y-4">
            {SCENES.map((scene) => (
              <section key={scene.id} className="space-y-2">
                <div className="text-[12px] font-semibold tracking-[0.12em] text-white/60 uppercase">
                  {scene.title}
                </div>
                <div className="flex flex-wrap gap-2">
                  <Button
                    testId={`scene-${scene.id}`}
                    tone="primary"
                    onClick={() => startScene(scene.open.message)}
                  >
                    ▶ {scene.open.label}
                  </Button>
                  {scene.then.map((step, i) => (
                    <Button
                      key={step.message}
                      testId={`scene-${scene.id}-then-${i}`}
                      onClick={() => followUp(step.message)}
                    >
                      {step.label}
                    </Button>
                  ))}
                </div>
                <p className="text-[12.5px] leading-snug text-white/50">{scene.hint}</p>
              </section>
            ))}
          </div>

          <div className="mt-5 grid grid-cols-2 gap-2 border-t border-white/10 pt-4">
            <Button
              testId="presenter-mine"
              disabled={busy !== null}
              onClick={() => void run("mine", mineBlock, "Block mined.")}
            >
              {busy === "mine" ? "Mining…" : "Mine block"}
            </Button>
            <Button
              testId="presenter-compromise"
              tone="danger"
              disabled={
                busy !== null ||
                chatBusy ||
                !sessionId ||
                state?.compromise_control?.enabled === false
              }
              onClick={() =>
                void run(
                  "compromise",
                  () =>
                    retryWhileBusy(() =>
                      runCompromise(sessionId!, ATTACK_REQUEST_SATS),
                    ),
                  "Simulation finished.",
                )
              }
            >
              {busy === "compromise"
                ? "Simulating…"
                : chatBusy
                  ? "Waiting for the shopper…"
                  : "Simulate compromised agent"}
            </Button>
            <Button
              testId="presenter-random-nonce"
              tone={randomNonce ? "danger" : "plain"}
              disabled={busy !== null || state?.random_nonce_signer == null}
              onClick={() =>
                void run(
                  "random-nonce",
                  () => setRandomNonce(!randomNonce),
                  randomNonce ? "Signer is honest again." : "Signer now cheats.",
                )
              }
            >
              Random-nonce signer: {randomNonce ? "on" : "off"}
            </Button>
            <Button
              testId="presenter-reset"
              tone={reset === "confirm" ? "danger" : "plain"}
              disabled={busy !== null || reset === "running"}
              onClick={() => void onReset()}
            >
              {reset === "confirm" ? "Click again to reset" : "Reset demo"}
            </Button>
          </div>

          {note && (
            <p data-testid="presenter-note" className="mt-3 text-[13px] text-white/70">
              {note}
            </p>
          )}
        </div>
      )}
    </>
  );
}
