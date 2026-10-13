"use client";

import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import Chat, { type ChatControls } from "@/components/Chat";
import Presenter from "@/components/Presenter";
import XrayView from "@/components/xray/XrayView.tsx";
import { useStory } from "@/components/xray/useStory.ts";
import { xrayStore } from "@/lib/store.ts";
import { stateStore } from "@/lib/stateStore.ts";
import { stepKey, type PaceMode } from "@/lib/director.ts";
import {
  agentIdForSession,
  budgetFor,
  lostToAttacker,
  storyNumbers,
} from "@/lib/balances.ts";

export default function Demo() {
  const [xrayOpen, setXrayOpen] = useState(false);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [chatBusy, setChatBusy] = useState(false);
  const controlsRef = useRef<ChatControls | null>(null);
  const events = useSyncExternalStore(
    xrayStore.subscribe,
    () => xrayStore.snapshot,
    () => xrayStore.snapshot,
  );
  const state = useSyncExternalStore(
    stateStore.subscribe,
    () => stateStore.snapshot,
    () => null,
  );

  // The story keeps running in shopper mode, so opening the x-ray never replays
  // it. Presenters step through it; ?autoplay=1 plays it by itself.
  const story = useStory(events, initialPace());

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.metaKey || e.ctrlKey || e.altKey || isTyping(e.target)) return;
      // Space on a focused button is that button's click.
      if (e.key === " " && (e.target as HTMLElement | null)?.tagName === "BUTTON") return;
      const action = stepKey(e.key);
      if (!action) return;
      e.preventDefault();
      if (action === "next") story.next();
      else story.back();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [story]);

  useEffect(() => {
    xrayStore.start();
    stateStore.start();
    return () => {
      xrayStore.stop();
      stateStore.stop();
    };
  }, []);

  useEffect(() => {
    if (events.length > 0) stateStore.refreshSoon();
  }, [events]);

  // Every balance on screen comes from this one derivation: live in the chat,
  // and as of the step on screen in the x-ray (the same once it catches up).
  const agentId = agentIdForSession(events, sessionId);
  const budget = budgetFor(state, events, agentId);
  const numbers = storyNumbers(
    state,
    events,
    agentId,
    story.playheadSeq,
    story.waiting === 0 && !story.reviewing,
  );

  return (
    <div className="flex h-screen overflow-hidden">
      <main
        className={`h-full min-w-0 transition-[width] duration-500 ${
          xrayOpen ? "w-1/3 py-4 pl-4" : "w-full"
        }`}
      >
        <div
          data-testid="chat-frame"
          className={
            xrayOpen
              ? "mx-auto h-full max-w-[480px] overflow-hidden rounded-[34px] border border-line bg-canvas shadow-[0_18px_50px_-24px_rgb(0_0_0/0.3)]"
              : "h-full"
          }
        >
        <Chat
          budget={budget}
          xrayOpen={xrayOpen}
          onToggleXray={() => setXrayOpen((v) => !v)}
          onSession={setSessionId}
          onBusy={setChatBusy}
          controlsRef={controlsRef}
        />
        </div>
      </main>
      {xrayOpen && (
        <section className="h-full w-2/3 min-w-0">
          <XrayView
            story={story}
            events={events}
            state={state}
            numbers={numbers}
          />
        </section>
      )}
      <Presenter
        controls={controlsRef}
        sessionId={sessionId}
        chatBusy={chatBusy}
        state={state}
        pace={story.mode}
        onPace={story.setMode}
      />
    </div>
  );
}

function initialPace(): PaceMode {
  if (typeof window === "undefined") return "presenter";
  return new URLSearchParams(window.location.search).get("autoplay") === "1"
    ? "auto"
    : "presenter";
}

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
