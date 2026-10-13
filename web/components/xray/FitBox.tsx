"use client";

import { useLayoutEffect, useRef, type ReactNode } from "react";

/** Below this the panel would be too small to read from the back of a room. */
const MIN_SCALE = 0.6;

/**
 * Shows its content at full size when it fits, and otherwise scales it down
 * (still using the full width) until it does: a stage panel must never spill
 * over the device strip above it or the numbers below.
 */
export function FitBox({
  children,
  testId,
  ...data
}: {
  children: ReactNode;
  testId?: string;
} & Record<`data-${string}`, string | undefined>) {
  const outerRef = useRef<HTMLDivElement | null>(null);
  const innerRef = useRef<HTMLDivElement | null>(null);

  const fit = () => {
    const outer = outerRef.current;
    const inner = innerRef.current;
    if (!outer || !inner) return;
    const width = outer.clientWidth;
    const height = outer.clientHeight;
    if (!width || !height) return;
    const shownHeight = (scale: number) => {
      inner.style.width = `${width / scale}px`;
      return inner.offsetHeight * scale;
    };
    let scale = 1;
    if (shownHeight(1) > height) {
      let lo = MIN_SCALE;
      let hi = 1;
      for (let i = 0; i < 8; i++) {
        const mid = (lo + hi) / 2;
        if (shownHeight(mid) <= height) lo = mid;
        else hi = mid;
      }
      scale = lo;
    }
    const top = Math.max(0, (height - shownHeight(scale)) / 2);
    inner.style.transform = `translate(0, ${top}px) scale(${scale})`;
    inner.dataset.scale = scale.toFixed(3);
  };

  // Every new step can change the content's height: refit before it paints.
  useLayoutEffect(fit);

  useLayoutEffect(() => {
    const outer = outerRef.current;
    const inner = innerRef.current;
    if (!outer || !inner) return;
    let frame = 0;
    const observer = new ResizeObserver(() => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(fit);
    });
    observer.observe(outer);
    observer.observe(inner);
    return () => {
      cancelAnimationFrame(frame);
      observer.disconnect();
    };
  }, []);

  return (
    <div ref={outerRef} data-testid={testId} {...data} className="relative min-h-0 flex-1 overflow-hidden">
      <div ref={innerRef} data-testid="fit-box" className="absolute top-0 left-0 origin-top-left">
        {children}
      </div>
    </div>
  );
}
