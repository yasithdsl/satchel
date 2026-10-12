# satchel
prepaid sats for your agents, seedless by design

## Prerequisites

- [uv](https://docs.astral.sh/uv/) (manages Python 3.12 and the workspace)
- Docker Desktop (for the local regtest bitcoind)

## Layout

| folder | what it is |
| --- | --- |
| `core/` | `satchel-core`: shared library, including the regtest bitcoind client |
| `vault/` | `satchel-vault`: offline master-seed holder that never signs |
| `signer/` | `satchel-signer`: offline signer, one child key per payment |
| `agent/` | `satchel-agent`: shopping agent that spends from prepaid envelopes |
| `marketplace/` | `satchel-marketplace`: demo marketplace |
| `approver/` | Node/TypeScript Ledger approval service (DMK + Speculos), not scaffolded yet |
| `web/` | Next.js x-ray / shopping UI, not scaffolded yet |
| `scripts/` | `regtest.py`: local bitcoind helper |
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
