"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  captionFor,
  newContext,
  observe,
  type Caption,
  type StoryContext,
} from "@/lib/caption.ts";
import { dwellMs, isLive } from "@/lib/director.ts";
import type { XrayEvent } from "@/lib/xray.ts";

export interface PlayedStep {
  key: number;
  event: XrayEvent;
  caption: Caption;
  ctx: StoryContext;
  /** Browser time the step reached the screen; 0 for history on load. */
  at: number;
}

const HISTORY = 60;

export interface Story {
  played: PlayedStep[];
  current: PlayedStep | null;
  playheadSeq: number;
}

/**
 * Plays captioned events one at a time at a readable pace. Everything in the
 * x-ray (caption, highlighted nodes, Ledger takeover, big moments) follows
 * this playhead so the room sees one step at a time.
 */
export function useStory(events: XrayEvent[]): Story {
  const [played, setPlayed] = useState<PlayedStep[]>([]);
  const [playheadSeq, setPlayheadSeq] = useState(0);
  const ctxRef = useRef<StoryContext>(newContext());
  const seenRef = useRef(0);
  const bootRef = useRef<string | null>(null);
  const queueRef = useRef<PlayedStep[]>([]);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const keyRef = useRef(0);

  const playNext = useCallback(() => {
    if (timerRef.current) return;
    const next = queueRef.current.shift();
    if (!next) {
      setPlayheadSeq(seenRef.current);
      return;
    }
    const step = { ...next, at: Date.now() };
    setPlayed((p) => [...p.slice(-(HISTORY - 1)), step]);
    setPlayheadSeq(step.event.seq);
    timerRef.current = setTimeout(() => {
      timerRef.current = null;
      playNext();
    }, dwellMs(step.caption, queueRef.current.length));
  }, []);

  useEffect(() => {
    const last = events[events.length - 1];
    if (!last) return;
    if (last.boot && last.boot !== bootRef.current) {
      if (bootRef.current !== null) {
        if (timerRef.current) clearTimeout(timerRef.current);
        timerRef.current = null;
        queueRef.current = [];
        setPlayed([]);
      }
      bootRef.current = last.boot;
      ctxRef.current = newContext();
      seenRef.current = 0;
    }
    const fresh = events.filter((e) => e.seq > seenRef.current);
    if (fresh.length === 0) return;
    seenRef.current = last.seq;
    const now = Date.now();
    const history: PlayedStep[] = [];
    for (const event of fresh) {
      ctxRef.current = observe(ctxRef.current, event);
      const caption = captionFor(event, ctxRef.current);
      if (!caption) continue;
      const step: PlayedStep = {
        key: ++keyRef.current,
        event,
        caption,
        ctx: ctxRef.current,
        at: 0,
      };
      if (isLive(event.ts, now)) queueRef.current.push(step);
      else history.push(step);
    }
    if (history.length > 0) {
      setPlayed((p) => [...p, ...history].slice(-HISTORY));
    }
    playNext();
  }, [events, playNext]);

  useEffect(
    () => () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    },
    [],
  );

  return {
    played,
    current: played[played.length - 1] ?? null,
    playheadSeq,
  };
}
