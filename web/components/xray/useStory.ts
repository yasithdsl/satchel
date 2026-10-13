"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  captionFor,
  newContext,
  observe,
  type Caption,
  type StoryContext,
} from "@/lib/caption.ts";
import { dwellMs, isLive, type PaceMode } from "@/lib/director.ts";
import type { XrayEvent } from "@/lib/xray.ts";

export interface PlayedStep {
  key: number;
  event: XrayEvent;
  caption: Caption;
  ctx: StoryContext;
  /** Browser time the step reached the screen; 0 for history on load. */
  at: number;
}

const HISTORY = 120;

export interface Story {
  /** Every step shown so far, oldest first. */
  played: PlayedStep[];
  /** The step on screen; earlier than the newest while reviewing. */
  current: PlayedStep | null;
  /** Steps before `current`, newest first (for the faint lines). */
  earlier: PlayedStep[];
  /** Highest event seq the audience has reached. */
  playheadSeq: number;
  /** Steps that happened but are not on screen yet. */
  waiting: number;
  reviewing: boolean;
  mode: PaceMode;
  setMode: (mode: PaceMode) => void;
  next: () => void;
  back: () => void;
}

/**
 * Turns the event stream into one step at a time. In presenter mode the
 * system keeps running but the story waits for the presenter to press next;
 * in auto mode steps play at a readable pace. Everything in the x-ray
 * (caption, highlighted nodes, panels, Ledger takeover, big moments) follows
 * the step on screen.
 */
export function useStory(events: XrayEvent[], initialMode: PaceMode = "presenter"): Story {
  const [played, setPlayed] = useState<PlayedStep[]>([]);
  const [cursor, setCursorState] = useState(-1);
  const [waiting, setWaiting] = useState(0);
  const [mode, setModeState] = useState<PaceMode>(initialMode);
  const ctxRef = useRef<StoryContext>(newContext());
  const seenRef = useRef(0);
  const bootRef = useRef<string | null>(null);
  const queueRef = useRef<PlayedStep[]>([]);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const keyRef = useRef(0);
  const modeRef = useRef<PaceMode>(initialMode);
  const playedLenRef = useRef(0);
  const cursorRef = useRef(-1);

  const setCursor = useCallback((value: number) => {
    cursorRef.current = value;
    setCursorState(value);
  }, []);

  const append = useCallback(
    (steps: PlayedStep[]) => {
      setPlayed((p) => [...p, ...steps].slice(-HISTORY));
      playedLenRef.current = Math.min(playedLenRef.current + steps.length, HISTORY);
      setCursor(playedLenRef.current - 1);
    },
    [setCursor],
  );

  const show = useCallback(() => {
    const next = queueRef.current.shift();
    setWaiting(queueRef.current.length);
    if (!next) return null;
    const step = { ...next, at: Date.now() };
    append([step]);
    return step;
  }, [append]);

  const autoPlay = useCallback(() => {
    if (timerRef.current || modeRef.current !== "auto") return;
    const step = show();
    if (!step) return;
    timerRef.current = setTimeout(() => {
      timerRef.current = null;
      autoPlay();
    }, dwellMs(step.caption, queueRef.current.length));
  }, [show]);

  const next = useCallback(() => {
    if (cursorRef.current < playedLenRef.current - 1) {
      setCursor(cursorRef.current + 1);
      return;
    }
    if (modeRef.current === "presenter") show();
  }, [setCursor, show]);

  const back = useCallback(() => {
    if (cursorRef.current > 0) setCursor(cursorRef.current - 1);
  }, [setCursor]);

  const setMode = useCallback(
    (m: PaceMode) => {
      modeRef.current = m;
      setModeState(m);
      if (m === "auto") {
        setCursor(playedLenRef.current - 1);
        autoPlay();
      } else if (timerRef.current) {
        clearTimeout(timerRef.current);
        timerRef.current = null;
      }
    },
    [autoPlay, setCursor],
  );

  useEffect(() => {
    const last = events[events.length - 1];
    if (!last) return;
    if (last.boot && last.boot !== bootRef.current) {
      if (bootRef.current !== null) {
        if (timerRef.current) clearTimeout(timerRef.current);
        timerRef.current = null;
        queueRef.current = [];
        playedLenRef.current = 0;
        setPlayed([]);
        setCursor(-1);
        setWaiting(0);
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
    if (history.length > 0) append(history);
    setWaiting(queueRef.current.length);
    autoPlay();
  }, [events, autoPlay, append, setCursor]);

  useEffect(
    () => () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    },
    [],
  );

  const current = cursor >= 0 ? (played[cursor] ?? null) : null;
  const newest = played[played.length - 1] ?? null;
  const caughtUp = waiting === 0 && current === newest;
  return {
    played,
    current,
    earlier: cursor > 0 ? played.slice(Math.max(0, cursor - 2), cursor).reverse() : [],
    playheadSeq: current ? (caughtUp ? seenRef.current : current.event.seq) : caughtUp ? seenRef.current : 0,
    waiting,
    reviewing: current !== null && current !== newest,
    mode,
    setMode,
    next,
    back,
  };
}
