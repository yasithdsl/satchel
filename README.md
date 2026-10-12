# satchel
prepaid sats for your agents, seedless by design

## Prerequisites

- [uv](https://docs.astral.sh/uv/) (manages Python 3.12 and the workspace)
- Docker Desktop (for the local regtest bitcoind)

## Layout

| folder | what it is |
| --- | --- |
| `core/` | `satchel-core`: shared library, including the regtest bitcoind client |
| `vault/` | `satchel-vault`: simulated air-gapped seed holder; never signs, never touches the network |
| `laptop/` | `satchel-laptop`: online coordinator; reads vault payloads over HTTP and overlays chain data |
| `signer/` | `satchel-signer`: offline signer, one child key per payment |
| `agent/` | `satchel-agent`: shopping agent and its prepaid envelope wallet |
| `marketplace/` | `satchel-marketplace`: demo marketplace |
| `approver/` | Node/TypeScript Ledger approval service (DMK + Speculos), not scaffolded yet |
| `web/` | Next.js x-ray / shopping UI, not scaffolded yet |
| `scripts/` | `regtest.py`: local bitcoind helper; `fund_envelopes.py`: faucet-fund envelopes |
| `tests/` | workspace-level tests |

## Quickstart

```sh
uv sync                                # create the venv and install the workspace

uv run scripts/regtest.py up           # start bitcoind, create/load the faucet wallet
uv run scripts/regtest.py fund <bcrt1 address> [sats]   # send sats (default 1000000) + mine a block
uv run scripts/regtest.py unspent <address> [...]       # list confirmed UTXOs

uv run pytest                          # unit tests; integration tests skip if the node is down

uv run scripts/regtest.py down         # stop bitcoind (chain state is kept)
docker compose down -v                 # stop and wipe the chain volume
```

The node listens on `http://127.0.0.1:18443` with RPC credentials
`satchel`/`satchel`. This is a local regtest node only; those credentials are
not used anywhere else. `RegtestNode` can also be configured via
`BITCOIND_RPC_URL`, `BITCOIND_RPC_USER`, and `BITCOIND_RPC_PASSWORD`.

## Ledger approver (Speculos)

```sh
cd approver && pnpm install && pnpm fetch-app && cd ..  # official Ethereum app ELF (Flex), sha256-pinned
docker compose --profile ledger up -d speculos          # emulated Ledger Flex; web UI at http://127.0.0.1:5001
(cd approver && pnpm start)                             # approver on 127.0.0.1:8003
curl -s 127.0.0.1:8003/address                          # the Ledger address to register in the vault
docker compose --profile ledger stop speculos
```

Plans go to `POST /approve`; the plain-English text appears on the Speculos screen and must be
approved there (manual by default). For rehearsals only, start the approver with
`SATCHEL_APPROVER_DEMO_AUTOMATION=1` to script approvals. See `approver/README.md`.

## Demo marketplace

```sh
uv run satchel-marketplace serve                        # 127.0.0.1:8004 (regtest only)
curl -s '127.0.0.1:8004/products/search?q=headphones&max_price_usd=200&deliver_by=2026-10-16'
curl -s -X POST 127.0.0.1:8004/checkout -H 'content-type: application/json' -d '{"product_id": "aurora-anc-wireless-headphones"}'
curl -s 127.0.0.1:8004/orders/<order_id>                # awaiting_payment / payment_pending / underpaid / paid
```

20 products in `marketplace/src/satchel_marketplace/catalogue.json` (headphones, laptops, kitchen,
accessories), priced in BTC at a fixed demo rate of $100,000/BTC. Each order gets a fresh address
from the node's `merchant` wallet and is marked paid once the payment has one confirmation.
Orders live in `.satchel/marketplace/orders.json` (`SATCHEL_MARKETPLACE_DIR`).

## Shopping agent

```sh
export ANTHROPIC_API_KEY=...                            # the agent uses claude-sonnet-5-5 (SATCHEL_AGENT_MODEL)
uv run satchel-laptop serve                             # coordinator flows: POST /grants, POST /spends
uv run satchel-agent serve                              # 127.0.0.1:8005
curl -N -X POST 127.0.0.1:8005/chat -H 'content-type: application/json' \
  -d '{"message": "Find me headphones under $200 that arrive by Friday."}'
uv run scripts/regtest.py miner --interval 10           # demo: mine a block every 10 s so payments confirm
```

`POST /chat` streams Server-Sent Events (`session`, `text`, `tool_call`, `tool_result`, `error`, `done`);
pass the returned `session_id` to continue a conversation, and `GET /sessions/{id}` shows its
history and budget. The agent's only key is the envelope it was granted; anything larger goes
through the laptop's large-spend flow and the Ledger. Service URLs: `SATCHEL_MARKETPLACE_URL`
(default `http://127.0.0.1:8004`), `SATCHEL_LAPTOP_URL` (default `http://127.0.0.1:8000`).
`SATCHEL_AGENT_DEMO_AUTO=approve` (with the approver's demo automation on) scripts Ledger
decisions for rehearsals only.

Demo only: start the agent with `SATCHEL_AGENT_DEMO_CONTROLS=1` to enable the simulated-compromise
control. `POST /demo/compromise {"session_id": ...}` runs a deterministic script (no LLM) as if an
attacker controlled the agent: it sends the whole envelope to a separate `loss-sink` wallet on the
node, then asks the laptop's large-spend flow for 0.05 BTC more to the same address, which lands on
the Ledger. `GET /demo/loss-sink` reports the sink's balance for the x-ray view.

## Vault and envelopes

```sh
export SATCHEL_VAULT_PASSPHRASE='choose-a-passphrase'   # or omit to be prompted
uv run satchel-vault setup --dice "<at least 20 dice rolls, digits 1-6>" --ledger-address 0x...
uv run satchel-vault allocate --count 3 --budget 50000  # prints the envelope address export
uv run satchel-vault serve                              # payload API on 127.0.0.1:8001
uv run scripts/fund_envelopes.py                        # faucet-funds unfunded envelopes + mines a block
uv run satchel-laptop serve                             # coordinator on 127.0.0.1:8000
curl -s 127.0.0.1:8000/envelopes                        # status + on-chain balance per envelope
uv run satchel-signer serve                             # signer on 127.0.0.1:8002 (POST /sign)
uv run satchel-vault reset --yes                        # demo only: wipe seed and inventory
```

The laptop package also runs the two coordinator flows, carrying payloads between vault, approver
and signer (it never derives or stores vault keys):

- `satchel_laptop.grant.grant_envelope(agent_id, budget_sats, ...)` picks the smallest funded,
  unassigned envelope that fits, gets the grant approved on the Ledger, has the vault release the
  key and hands it to the agent's envelope wallet.
- `uv run scripts/fund_main_funds.py` funds a few vault receive addresses from the faucet; then
  `satchel_laptop.spend.large_spend(destination, amount_sats, purpose, ...)` selects UTXOs, builds
  the PSBT (change to a fresh hardened vault change address), gets it approved on the Ledger, has
  the vault release only the input keys, the signer sign and the vault verify, and broadcasts only
  through `broadcast_verified(node, signed_tx, verification_pass)`.

Every hop emits an event and is recorded with its QR-ready payload (key releases redacted) in
`.satchel/laptop/flows/<flow_id>.json`. Service URLs: `SATCHEL_VAULT_URL`, `SATCHEL_APPROVER_URL`
(default `http://127.0.0.1:8003`), `SATCHEL_SIGNER_URL` (default `http://127.0.0.1:8002`).

Keys only leave the vault with a Ledger approval: `POST /release/envelope` (envelope grant) and
`POST /release/spend` (large spend plus its unsigned PSBT). Each approval must recover to the
registered Ledger address, match the text the vault rebuilds from the plan, be unexpired and use
a fresh nonce; spend PSBTs must match the approved hash, amount and destination.

Before anything is broadcast, the vault's `POST /verify` checks the signer's transaction
against the approved PSBT and recomputes every signature byte for byte.

Demo only: start the signer with `SATCHEL_SIGNER_RANDOM_NONCE=1`, or toggle it live with
`curl -X POST 127.0.0.1:8002/demo/random-nonce -H 'content-type: application/json' -d '{"enabled": true}'`.
It then signs with plain random nonces: the network accepts the transaction, but vault verification fails it.

State lives in `.satchel/` (gitignored): `SATCHEL_VAULT_DIR` (default
`.satchel/vault`), `SATCHEL_LAPTOP_DIR` (default `.satchel/laptop`) and the
event log `SATCHEL_EVENT_LOG` (default `.satchel/events.jsonl`). The laptop finds
the vault via `SATCHEL_VAULT_URL` (default `http://127.0.0.1:8001`).
