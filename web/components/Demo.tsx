"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Chat from "@/components/Chat";
import XrayPanel from "@/components/XrayPanel";
import { xrayStore } from "@/lib/store.ts";
import type { DeviceHandle } from "@/components/xray/Device.tsx";

export default function Demo() {
  const [xrayOpen, setXrayOpen] = useState(false);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const sendRef = useRef<(text: string) => void>(() => {});
  const deviceRef = useRef<DeviceHandle | null>(null);

  useEffect(() => {
    xrayStore.start();
    return () => xrayStore.stop();
  }, []);

  const openLedger = useCallback(() => {
    setXrayOpen(true);
    requestAnimationFrame(() =>
      requestAnimationFrame(() => deviceRef.current?.focus()),
    );
  }, []);

  return (
    <div className="relative flex h-screen overflow-hidden">
      <main
        className={`flex h-full min-w-0 justify-center transition-all duration-500 ${
          xrayOpen ? "w-[40%]" : "w-full"
        }`}
      >
        <Chat
          onSession={setSessionId}
          sendRef={sendRef}
          onOpenLedger={openLedger}
        />
      </main>
      <section
        className={`h-full min-w-0 transition-all duration-500 ${
          xrayOpen ? "w-[60%]" : "w-0 overflow-hidden"
        }`}
      >
        <XrayPanel
          open={xrayOpen}
          sessionId={sessionId}
          onClose={() => setXrayOpen(false)}
          onSendMessage={(m) => sendRef.current?.(m)}
          deviceRef={deviceRef}
        />
      </section>
      {!xrayOpen && (
        <button
          type="button"
          onClick={() => setXrayOpen(true)}
          className="absolute top-3 right-3 z-30 rounded-full border border-neutral-200 bg-white/80 px-3 py-1 text-xs text-neutral-500 shadow-sm backdrop-blur transition hover:text-neutral-800"
        >
          X-ray
        </button>
      )}
    </div>
  );
}
