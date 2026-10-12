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
