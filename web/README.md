# web

The Satchel demo UI. Shopper mode is a consumer chat with the shopping agent; the X-ray switch splits
the screen and tells the story one step at a time (caption bar, device strip, big numbers, Ledger
takeover). Press P for the presenter drawer.

```sh
pnpm install
pnpm dev              # http://localhost:3100 (start the backend first: uv run scripts/demo_reset.py)
pnpm typecheck && pnpm test && pnpm build && pnpm e2e   # e2e mocks the backends (port 3200)
pnpm e2e:real         # all three scenes through the presenter drawer, real Claude, 1920x1080
```

Where things live:

- `lib/caption.ts`: the one plain-English sentence for every event type (or why it stays silent).
  `test/caption.test.ts` fails if a known event type has neither, or if a caption ever contains an
  id, address or sats count.
- `components/xray/useStory.ts`: plays captions at a readable pace; the caption, highlighted nodes,
  Ledger takeover and big moments all follow its playhead.
- `lib/balances.ts`: the single derivation behind the budget pill and the numbers row.
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
