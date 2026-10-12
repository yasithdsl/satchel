#!/bin/sh
# Downloads the official Ledger Ethereum app ELF (Flex build, release 1.22.3)
# into approver/apps/ and verifies its pinned SHA-256. Idempotent.
set -eu

APP_DIR="$(cd "$(dirname "$0")/.." && pwd)/apps"
ELF="$APP_DIR/app-1.22.3-flex.elf"
URL="https://github.com/LedgerHQ/app-ethereum/releases/download/1.22.3/app-1.22.3-flex.elf"
SHA256="88ce93fe2b982c05f37aef108c1ea40f251ae394c25bb8232eb6a8adb3feaa5d"

mkdir -p "$APP_DIR"

verify() {
  [ -f "$ELF" ] || return 1
  actual="$(shasum -a 256 "$ELF" | awk '{print $1}')"
  [ "$actual" = "$SHA256" ]
}

if verify; then
  echo "already present and verified: $ELF" >&2
  exit 0
fi

echo "downloading $URL" >&2
curl -fsSL "$URL" -o "$ELF.tmp"
mv "$ELF.tmp" "$ELF"

if ! verify; then
  rm -f "$ELF"
  echo "sha256 mismatch for $ELF; deleted" >&2
  exit 1
fi

echo "verified sha256 $SHA256: $ELF" >&2
