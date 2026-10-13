import type { Page } from "@playwright/test";

/** Screen sizes the x-ray must fit: projectors, laptops (browser chrome included) and desktops. */
export const SCREENS = [
  { width: 1920, height: 1080 },
  { width: 2560, height: 1440 },
  { width: 1728, height: 1000 },
  { width: 1512, height: 845 },
  { width: 1440, height: 900 },
  { width: 1440, height: 760 },
  { width: 1366, height: 768 },
  { width: 1280, height: 720 },
];

/** Stops CSS animations and transitions so a check sees the settled page. */
export async function settleAnimations(page: Page) {
  await page.addStyleTag({
    content:
      "*,*::before,*::after{animation-duration:0s!important;animation-delay:0s!important;" +
      "transition-duration:0s!important;transition-delay:0s!important}",
  });
}

/**
 * What is wrong with the x-ray layout on screen right now: regions that overlap,
 * content that spills out of its region, and text that is cut off.
 */
export async function layoutProblems(page: Page): Promise<string[]> {
  return page.evaluate(() => {
    const problems: string[] = [];
    const T = 1;
    const byId = (id: string) => document.querySelector<HTMLElement>(`[data-testid="${id}"]`);
    const box = (el: Element) => el.getBoundingClientRect();
    const inside = (r: DOMRect, b: DOMRect) =>
      r.left >= b.left - T && r.right <= b.right + T && r.top >= b.top - T && r.bottom <= b.bottom + T;
    const name = (el: Element) => {
      const id = el.getAttribute("data-testid");
      const text = (el.textContent ?? "").trim().replace(/\s+/g, " ").slice(0, 40);
      return `${el.tagName.toLowerCase()}${id ? `[${id}]` : ""} "${text}"`;
    };
    const visible = (el: Element) => {
      const r = box(el);
      if (r.width === 0 || r.height === 0) return false;
      const style = getComputedStyle(el);
      return style.visibility !== "hidden" && style.display !== "none";
    };

    const doc = document.documentElement;
    if (doc.scrollWidth > window.innerWidth + T || doc.scrollHeight > window.innerHeight + T) {
      problems.push(`page scrolls (${doc.scrollWidth}x${doc.scrollHeight})`);
    }

    const toggle = document.querySelector('[role="switch"]');
    if (toggle && box(toggle).height > 48) problems.push("chat header: the X-ray switch wraps");

    const frame = byId("chat-frame");
    if (frame && frame.parentElement && !inside(box(frame), box(frame.parentElement))) {
      problems.push("chat frame spills out of its column");
    }

    const panel = byId("xray-panel");
    if (!panel) return problems;
    const panelBox = box(panel);
    if (panel.scrollHeight > panel.clientHeight + T) problems.push("x-ray scrolls");

    const order = [
      "caption-bar",
      "device-strip",
      "stage-panel",
      "ledger-takeover",
      "numbers-row",
      "xray-footer",
    ];
    const regions = order
      .map((id) => [id, byId(id)] as const)
      .filter((r): r is readonly [string, HTMLElement] => r[1] !== null && visible(r[1]));
    for (let i = 1; i < regions.length; i++) {
      const [aId, a] = regions[i - 1];
      const [bId, b] = regions[i];
      const overlap = box(a).bottom - box(b).top;
      if (overlap > T) problems.push(`${aId} overlaps ${bId} by ${Math.round(overlap)}px`);
    }

    const banner = byId("moment-banner");
    const checked: (readonly [string, HTMLElement])[] = [...regions];
    if (banner && visible(banner)) checked.push(["moment-banner", banner]);

    for (const [id, region] of checked) {
      const regionBox = box(region);
      if (!inside(regionBox, panelBox)) problems.push(`${id} spills out of the x-ray`);
      // The caption bar clips its older lines on purpose; it is checked below.
      if (id === "caption-bar") continue;
      for (const el of region.querySelectorAll("*")) {
        if (!visible(el) || el.closest("[data-layout-free]")) continue;
        if (!inside(box(el), regionBox)) {
          problems.push(`${id}: ${name(el)} spills out`);
          break;
        }
      }
    }

    const bar = byId("caption-bar");
    if (bar && visible(bar)) {
      const barBox = box(bar);
      const earlier = [...bar.querySelectorAll('[data-testid="caption-earlier"]')];
      const earlierBox = earlier[0]?.parentElement ? box(earlier[0].parentElement) : null;
      for (const id of ["caption", "caption-why"]) {
        const el = byId(id);
        if (!el || !visible(el)) continue;
        if (!inside(box(el), barBox)) problems.push(`caption bar: ${id} spills out`);
        if (earlierBox && box(el).bottom > earlierBox.top + T) {
          problems.push(`caption bar: ${id} overlaps the earlier lines`);
        }
      }
      if (earlierBox) {
        for (const line of earlier) {
          const r = box(line);
          const shown =
            r.bottom > earlierBox.top + T &&
            r.top < earlierBox.bottom - T &&
            r.right > earlierBox.left + T &&
            r.left < earlierBox.right - T;
          if (shown && !inside(r, earlierBox)) problems.push(`caption bar: ${name(line)} is half cut`);
        }
      }
    }

    // Text cut by an ellipsis or a line clamp.
    for (const el of panel.querySelectorAll<HTMLElement>("*")) {
      if (!visible(el) || el.closest("[data-layout-free]") || el.closest('[data-testid="details-drawer"]')) {
        continue;
      }
      const style = getComputedStyle(el);
      const clamped = style.webkitLineClamp !== "none" && style.webkitLineClamp !== "";
      if (style.textOverflow === "ellipsis" && el.scrollWidth > el.clientWidth + T) {
        problems.push(`text cut: ${name(el)}`);
      } else if (clamped && el.scrollHeight > el.clientHeight + T) {
        problems.push(`text cut: ${name(el)}`);
      }
    }
    return problems;
  });
}
