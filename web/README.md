# web

The Satchel demo UI: a consumer-style chat with the shopping agent, plus an x-ray panel that shows
each layer (agent, envelope, laptop, Ledger, vault, signer, marketplace, loss sink) as it acts.

```sh
pnpm install
pnpm dev              # http://localhost:3100 (start the backend first: uv run scripts/demo_reset.py)
pnpm typecheck && pnpm test && pnpm build && pnpm e2e   # e2e mocks the backends (port 3200)
```

Backend URLs: `NEXT_PUBLIC_AGENT_URL` (default http://127.0.0.1:8005), `NEXT_PUBLIC_XRAY_URL`
(http://127.0.0.1:8006), `NEXT_PUBLIC_SPECULOS_URL` (http://127.0.0.1:5001). Dependencies must be at
least 7 days old (`minimumReleaseAge` in `pnpm-workspace.yaml`).
