# approver

The Ledger approval device for the Prepaid Agents demo. It talks to the
Speculos emulator over Ledger's Device Management Kit (DMK) — the same SDK a
real wallet integration uses — so the approval flow against real hardware is
identical. In this part it proves the path end to end: connect, open a
session, confirm the Ethereum app is running, and derive an address.

Everything is demo/dev tooling only: Speculos runs with its built-in default
seed and the speculos DMK transport.

## Requirements

- Node.js 26+ (TypeScript runs natively via type stripping — no build step)
- pnpm 10+
- Docker (for Speculos and bitcoind)

## The Ethereum app binary

Speculos needs the compiled Ledger app ELF. `scripts/fetch-eth-app.sh`
downloads the official Flex build from the app-ethereum GitHub release:

- URL: https://github.com/LedgerHQ/app-ethereum/releases/download/1.22.3/app-1.22.3-flex.elf
- Pinned SHA-256: `88ce93fe2b982c05f37aef108c1ea40f251ae394c25bb8232eb6a8adb3feaa5d`

The file lands in `approver/apps/` (gitignored) and the script refuses to keep
anything that does not match the pinned hash.

Alternative, documented by Ledger: build the app from source inside Ledger's
`ledger-app-builder` container (`make BOLOS_SDK=$FLEX_SDK` in a checkout of
app-ethereum). The pinned release ELF above is the simpler path.

## Commands

```bash
pnpm install            # installs locked deps (see dependency policy below)
pnpm typecheck          # tsc --noEmit
pnpm test               # offline unit tests
pnpm fetch-app          # download + verify the Ethereum app ELF
pnpm derive-address     # connect to Speculos, print the ETH address JSON
```

## Running Speculos

Run the compose commands from the repository root, and the `pnpm` commands
from `approver/`:

```bash
# start the emulator (profile keeps it out of `docker compose up`)
docker compose --profile ledger up -d speculos

# the Speculos HTTP API / web UI is on the host at:
open http://127.0.0.1:5001

# what the emulated screen shows right now:
curl -s 'http://127.0.0.1:5001/events?currentscreenonly=true'

# stop it
docker compose --profile ledger stop speculos
```

Then:

```bash
pnpm derive-address
# {"address":"0x…","path":"44'/60'/0'/0/0"}
```

`SPECULOS_URL` overrides the emulator URL (default `http://127.0.0.1:5001`).

## The approver service

```bash
SATCHEL_APPROVER_DEMO_AUTOMATION=1 pnpm start   # 127.0.0.1:APPROVER_PORT (8003)
```

- `GET /health` → `{"ok": true, "demo_automation": bool}`
- `GET /address` → `{"address", "path"}` (`44'/60'/0'/0/0`)
- `POST /approve` body `{"plan": {...}, "demo_auto"?: "approve"|"reject"}` →
  `200` `toHttp("ledger_approval")` · `409` rejected on device · `409` device
  busy · `422` invalid plan · `403` demo_auto while automation is off ·
  `504` timeout · `502` other device errors
- Only when automation is on: `GET /demo/screen`, `GET /demo/screenshot`,
  `POST /demo/approve`, `POST /demo/reject`

`demo_auto` and the `/demo/*` routes exist only with
`SATCHEL_APPROVER_DEMO_AUTOMATION` (`1|true|yes`) — they drive the Speculos
screen for demos instead of a human finger. `SPECULOS_URL` overrides the API
URL (default `http://127.0.0.1:5001`).

### Flex review flow (Ethereum app 1.22.3, discovered by experiment)

Personal-message review on Flex (480×600), driven via the Speculos `/finger`
API (`{"action":"press-and-release","x",...,"x2","y2"}` for taps and swipes,
`press`/`release` for holds):

1. **Page 1**: "Review message" — "Swipe to review", a `Reject` button bottom
   left, page indicator `1 of N` bottom right.
2. **Middle pages**: the message fields. Advance by swiping right→left
   (press ~(400,300), release ~(80,300)).
3. **Last page**: "Sign message?" and a `Hold to sign` bar. **Approve** =
   press and hold the bar's centre for ~4 s, release → "Message signed".
4. **Reject** = tap `Reject` → confirmation screen → tap `Yes, reject`
   ("Go back to message" is the other choice) → "Message rejected".

`src/speculos.ts` is text-driven: it polls `/events?currentscreenonly=true`,
pages until it sees a `Hold to …` control, and taps controls by their
reported bounding boxes rather than fixed coordinates.

## Dependency policy

Dependencies must be published at least 7 days before they are installed.
`pnpm-workspace.yaml` sets `minimumReleaseAge: 10080` (minutes), which pnpm
enforces at resolution time — a version younger than 7 days cannot be
installed even if it is `latest`.
