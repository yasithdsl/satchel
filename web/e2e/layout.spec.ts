import { mkdirSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { expect, test, type Page } from "@playwright/test";
import { layoutProblems, SCREENS, settleAnimations } from "./layout";
import { mockBackends, sse } from "./mocks";

type Event = Record<string, unknown> & { payload?: Record<string, unknown> | null };

/** A real three-scene run (see test/fixtures), replayed as if it just happened. */
function freshRun(): Event[] {
  const run = JSON.parse(
    readFileSync(resolve(process.cwd(), "test/fixtures/demo-events.json"), "utf8"),
  ) as Event[];
  const now = Date.now();
  return run.map((e, i) => ({
    ...e,
    ts: new Date(now - (run.length - i) * 20).toISOString(),
    payload: e.payload && "session_id" in e.payload ? { ...e.payload, session_id: "s-x" } : e.payload,
  }));
}

function finalState(run: Event[]) {
  const envelopes = run
    .filter((e) => e.type === "wallet_loaded")
    .map((e) => ({
      index: e.payload!.envelope_index,
      budget_sats: e.payload!.budget_sats,
      assigned_to: e.payload!.agent_id,
      status: "assigned",
      balance_sats: e.payload!.budget_sats,
      available_sats: e.payload!.budget_sats,
    }));
  return {
    ts: new Date().toISOString(),
    main_funds: {
      fingerprint: "f",
      addresses: 3,
      utxos: 3,
      balance_sats: 99_499_300,
      available_sats: 99_499_300,
    },
    envelopes,
    loss_sink: { wallet: "loss-sink", confirmed_sats: 199_800, pending_sats: 0, last_address: null },
    random_nonce_signer: false,
    compromise_control: { enabled: true },
    pending_approval: { pending: null },
    errors: {},
  };
}

const SESSION = sse([
  { type: "session", session_id: "s-x" },
  { type: "text", delta: "Hello." },
  { type: "done" },
]);

async function open(page: Page, run: Event[], state: Record<string, unknown>) {
  await mockBackends(page, { chatBodies: [SESSION], xrayState: state, xrayWaves: [run] });
  await page.goto("/");
  await settleAnimations(page);
  await page.getByLabel("Message").fill("hi");
  await page.getByRole("button", { name: "Send" }).click();
  await expect(page.getByText("Hello.")).toBeVisible();
  await page.getByRole("switch", { name: "X-ray" }).click();
  await expect(page.getByTestId("xray-panel")).toBeVisible();
  await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur());
}

async function nextFrame(page: Page) {
  await page.evaluate(
    () => new Promise((done) => requestAnimationFrame(() => requestAnimationFrame(done))),
  );
}

for (const screen of SCREENS) {
  test(`every step of a real run fits at ${screen.width}x${screen.height}`, async ({ page }, info) => {
    test.setTimeout(120_000);
    await page.setViewportSize(screen);
    const run = freshRun();
    await open(page, run, finalState(run));
    const status = page.getByTestId("step-status");
    await expect(status).toHaveText(/more steps?/, { timeout: 15_000 });

    const failures: string[] = [];
    const smallest: Record<string, number> = {};
    const shots = resolve(info.outputDir, "layout");
    mkdirSync(shots, { recursive: true });
    for (let step = 1; step < 400; step++) {
      const before = await status.innerText();
      if (before === "Up to date") break;
      await page.keyboard.press("ArrowRight");
      await expect(status).not.toHaveText(before);
      await nextFrame(page);
      const fit = await page.evaluate(() => {
        const stage = document.querySelector('[data-testid="stage-panel"]');
        const box = document.querySelector<HTMLElement>('[data-testid="fit-box"]');
        return stage && box ? { visual: stage.getAttribute("data-visual")!, scale: Number(box.dataset.scale) } : null;
      });
      if (fit) smallest[fit.visual] = Math.min(smallest[fit.visual] ?? 1, fit.scale);
      const problems = await layoutProblems(page);
      if (problems.length) {
        const caption = await page.getByTestId("caption").innerText();
        failures.push(`step ${step} "${caption}": ${problems.join("; ")}`);
        if (failures.length <= 4) await page.screenshot({ path: resolve(shots, `step-${step}.png`) });
      }
    }
    await expect(status).toHaveText("Up to date");
    info.annotations.push({ type: "smallest panel scale", description: JSON.stringify(smallest) });
    console.log(`${screen.width}x${screen.height} smallest panel scale ${JSON.stringify(smallest)}`);
    expect(failures).toEqual([]);
  });
}

const GRANT =
  "Create a 0.002 BTC satchel #1 for shopper-3c483daf from main funds. Approval valid until 13 Oct 10:10 UTC. Nonce 157c097c898dbb12";

for (const screen of SCREENS) {
  test(`the Ledger takeover fits at ${screen.width}x${screen.height}`, async ({ page }) => {
    await page.setViewportSize(screen);
    const run = freshRun();
    const upTo = run.findIndex((e) => e.type === "approval_requested");
    const live = run.slice(0, upTo + 1);
    const state = {
      ...finalState(run),
      pending_approval: {
        pending: {
          kind: "satchel_grant",
          text: GRANT,
          nonce: "157c097c898dbb12",
          started_at: new Date().toISOString(),
        },
      },
    };
    await mockBackends(page, {
      chatBodies: [SESSION],
      xrayState: state,
      xrayWaves: [live],
      ledgerTexts: ["Review satchel"],
    });
    await page.goto("/");
    await settleAnimations(page);
    await page.getByRole("switch", { name: "X-ray" }).click();
    await expect(page.getByTestId("step-status")).toHaveText(/more steps?/, { timeout: 15_000 });
    const takeover = page.getByTestId("ledger-takeover");
    for (let i = 0; i < 40 && !(await takeover.isVisible()); i++) {
      await page.keyboard.press("ArrowRight");
      await nextFrame(page);
    }
    await expect(takeover).toBeVisible();
    await nextFrame(page);
    expect(await layoutProblems(page)).toEqual([]);
  });
}
