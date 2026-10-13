"use client";

import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import Chat, { type ChatControls } from "@/components/Chat";
import Presenter from "@/components/Presenter";
import XrayView from "@/components/xray/XrayView.tsx";
import { useStory } from "@/components/xray/useStory.ts";
import { xrayStore } from "@/lib/store.ts";
import { stateStore } from "@/lib/stateStore.ts";
import {
  agentIdForSession,
  attackSeen,
  budgetFor,
  lostToAttacker,
  mainFunds,
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

  // The story keeps playing in shopper mode, so opening the x-ray never replays it.
  const story = useStory(events);

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

  // Every balance on screen comes from this one derivation.
  const budget = budgetFor(state, events, agentIdForSession(events, sessionId));
  const lost = lostToAttacker(state, events);

  return (
    <div className="flex h-screen overflow-hidden">
      <main
        className={`h-full min-w-0 transition-[width] duration-500 ${
          xrayOpen ? "w-1/2" : "w-full"
        }`}
      >
        <Chat
          budget={budget}
          xrayOpen={xrayOpen}
          onToggleXray={() => setXrayOpen((v) => !v)}
          onSession={setSessionId}
          onBusy={setChatBusy}
          controlsRef={controlsRef}
        />
      </main>
      {xrayOpen && (
        <section className="h-full w-1/2 min-w-0">
          <XrayView
            story={story}
            events={events}
            state={state}
            budget={budget}
            mainFundsSats={mainFunds(state)}
            lostSats={lost}
            showLost={attackSeen(events) || lost > 0}
          />
        </section>
      )}
      <Presenter
        controls={controlsRef}
        sessionId={sessionId}
        chatBusy={chatBusy}
        state={state}
      />
    </div>
  );
}
