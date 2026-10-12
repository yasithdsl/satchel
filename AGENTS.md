Project: Prepaid Agents. A Bitcoin custody setup for AI agents where no single device can steal the main funds, built for a Ledger-sponsored hackathon (theme: AI agents using Ledger as the trust layer).

The system has five parts. The vault is an offline device that holds the master seed and never signs anything. The signer is a separate offline device that signs transactions using only the specific child keys it is given for that payment, and is assumed to be potentially malicious. Envelopes are small prepaid budgets, each sitting on its own fully hardened key, which can be handed to an AI agent so it can spend without asking. The Ledger is the human approval device: the vault only releases keys when it sees a Ledger signature over a plain-English plan. The shopping agent is the user-facing product and talks to a demo marketplace.

Key decisions that every part must follow:
- All key derivation is fully hardened at every level. Receive keys use m/84'/1'/0'/0'/i', change keys use m/84'/1'/0'/1'/i', and envelope keys use m/84'/1'/0'/2'/i'. Hardening matters because with normal derivation, one leaked child key plus the xpub reveals the whole wallet.
- Addresses are native SegWit (P2WPKH) on Bitcoin regtest only. Never write code that can touch mainnet.
- The vault never signs. Only the signer and the agent's envelope wallet sign.
- All honest signing uses one shared deterministic signing function (RFC6979 nonces) from the core library, so the vault can recompute any honest signature byte for byte.
- Security decisions are made by deterministic code, never by the LLM. The agent only requests actions.
- Every payload that crosses a device boundary (vault, signer, Ledger approver, laptop) is serialised in a QR-ready format, even though the demo moves it over local HTTP. The UI shows these as QR codes.
- Every significant action emits an event to the shared event stream so the x-ray UI can show it.

Stack: Python 3.12 managed with uv for the core library, vault, signer, envelope wallet, marketplace and agent. embit for Bitcoin primitives. FastAPI for small local services. bitcoind in Docker for regtest. The Anthropic Python SDK for the agent. A small Node/TypeScript service using Ledger's Device Management Kit with the Speculos emulator for Ledger approvals. Next.js for the web UI.

Working style: make small, reviewable changes. Write tests for anything security-relevant. Prefer clear code over clever code. When a ticket is done, stop and summarise what you built, which files changed, how to run and test it, and anything you were unsure about.

Commands:
- `uv sync` installs the whole workspace (Python packages are `satchel_core`, `satchel_vault`, `satchel_laptop`, `satchel_signer`, `satchel_agent`, `satchel_marketplace`).
- The vault simulates an air-gapped device: it never imports network code or signing functions (enforced by `vault/tests/test_vault_boundaries.py`). The online `laptop` service reads vault payloads over HTTP and adds chain data.
- `uv run satchel-signer serve` runs the signer (port 8002); it never stores keys or broadcasts (enforced by `signer/tests/test_signer_boundaries.py`). Vault `POST /verify` (in `satchel_vault/verification.py`, the only vault module allowed to call `sign_digest`) must pass before any broadcast. The demo-only random-nonce signer (`satchel_signer/random_nonce.py`, flag `SATCHEL_SIGNER_RANDOM_NONCE` or `POST /demo/random-nonce`) is the only other file allowed a signing primitive (`tests/test_signing_path.py`); it must never be used outside the signer.
- Ledger approvals: `approver/` (Node/TypeScript, pnpm, DMK + Speculos; deps must be ≥7 days old, enforced by `minimumReleaseAge`). `cd approver && pnpm fetch-app`, `docker compose --profile ledger up -d speculos` (API/UI on 127.0.0.1:5001), `pnpm start` (port 8003), `pnpm typecheck && pnpm test`. DMK skills live in `.agents/skills/`; read them before touching approver code. The plan-text format is shared with the vault via `fixtures/approval_text_vectors.json` — change both sides together. Keys leave the vault only via `satchel_vault/release.py` after `approvals.validate_approval`. Tests marked `speculos` need Speculos running.
- `uv run satchel-vault setup|allocate|serve|reset` runs the vault (passphrase from `SATCHEL_VAULT_PASSPHRASE` or a prompt); `uv run satchel-laptop serve` runs the coordinator; `uv run scripts/fund_envelopes.py` funds allocated envelopes from the faucet. State lives under `.satchel/`.
- `uv run scripts/regtest.py up` starts regtest bitcoind in Docker and makes sure the faucet wallet has spendable coins. `down` stops it; `docker compose down -v` wipes chain state.
- `uv run scripts/regtest.py fund <bcrt1 address> [sats]` funds an address and mines a confirming block; `unspent <address>...` lists its UTXOs.
- `uv run pytest` runs all tests. Tests marked `regtest` skip when the node is down.
