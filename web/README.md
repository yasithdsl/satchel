# web

The Satchel demo UI. Shopper mode is a consumer chat with the shopping agent; the X-ray switch puts
the chat in a phone-width third and tells the story in the other two thirds, one step at a time
(caption bar, device strip, a stage panel per chapter, big numbers, Ledger takeover). The presenter
steps with → and ← (`?autoplay=1` plays on a timer). Press P for the presenter drawer.

```sh
pnpm install
pnpm dev              # http://localhost:3100 (start the backend first: uv run scripts/demo_reset.py)
pnpm typecheck && pnpm test && pnpm build && pnpm e2e   # e2e mocks the backends (port 3200)
pnpm e2e:real         # a presenter steps through all three scenes, real Claude, 1920x1080
SATCHEL_REAL_VIEWPORT=1512x845 pnpm e2e:real   # the same on a laptop-sized window
```

Where things live:

- `lib/caption.ts`: the one plain-English sentence for every event type (or why it stays silent).
  `test/caption.test.ts` fails if a known event type has neither, or if a caption ever contains an
  id, address or sats count.
- `components/xray/useStory.ts`: the playhead. In presenter mode (the default) a step shows only when
  the presenter presses →; in auto mode steps play on a timer. The caption, highlighted nodes, stage
  panel, Ledger takeover, big moments and numbers all follow it.
- `components/xray/panels/`: the stage panel for each chapter (satchel, store, attack, signer), drawn
  from the story context that `lib/caption.ts` builds up as events play. Panels sit in
  `components/xray/FitBox.tsx`, which scales a panel down when the window is too short for it, so it
  never overlaps the strip or the numbers. The `short:` variant (`app/globals.css`) tightens spacing on
  laptop-height windows.
- `e2e/layout.spec.ts`: replays a real three-scene run (`test/fixtures/demo-events.json`) step by step
  at eight screen sizes, from 1280x720 to 2560x1440, and fails on any overlap, spill or cut-off text
  (`e2e/layout.ts`). `pnpm e2e:real` runs the same check at every step it takes.
- `lib/balances.ts`: the single derivation behind the budget pill (live) and the numbers row (as of
  the step on screen, matching live once the story catches up).
- `lib/scenes.ts`: the presenter's scripted messages, kept in step with `scripts/demo_scenarios.py`.

Audience rules: no transaction ids, order ids, addresses, keys or raw sats in either view, USD first,
and no raw error text or status codes (errors go to the developer console; the screen shows a calm
retry). `pnpm e2e:real` checks the visible text for all of these at every step and fails if the
x-ray ever scrolls. It saves each scene's big moment to `../docs/screenshots/`.

`pnpm e2e:real` targets http://localhost:3100 by default; set `SATCHEL_REAL_URL` to test a production
build on another port (allow that origin with `SATCHEL_WEB_ORIGINS` when running the reset).

Backend URLs: `NEXT_PUBLIC_AGENT_URL` (default http://127.0.0.1:8005), `NEXT_PUBLIC_XRAY_URL`
(http://127.0.0.1:8006). Dependencies must be at least 7 days old (`minimumReleaseAge` in
`pnpm-workspace.yaml`).
