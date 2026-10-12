"use client";

import { useState } from "react";
import Chat from "@/components/Chat";
import XrayPanel from "@/components/XrayPanel";

export default function Demo() {
  const [xrayOpen, setXrayOpen] = useState(false);
  const [sessionId, setSessionId] = useState<string | null>(null);

  return (
    <div className="relative flex h-screen overflow-hidden">
      <main
        className={`flex h-full min-w-0 flex-1 justify-center transition-all duration-300 ${
          xrayOpen ? "max-w-[calc(100%-26rem)]" : ""
        }`}
      >
        <Chat onSession={setSessionId} />
      </main>
      <button
        type="button"
        onClick={() => setXrayOpen((v) => !v)}
        className="absolute top-3 right-3 z-30 rounded-full border border-neutral-200 bg-white/80 px-3 py-1 text-xs text-neutral-500 shadow-sm backdrop-blur transition hover:text-neutral-800"
      >
        X-ray
      </button>
      <XrayPanel
        open={xrayOpen}
        sessionId={sessionId}
        onClose={() => setXrayOpen(false)}
      />
    </div>
  );
}
