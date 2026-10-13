"""Operator console for the air-gapped vault device."""

import argparse
import getpass
import os
import sys

from .vault import Vault


def _passphrase(confirm: bool = False) -> str:
    stored = os.environ.get("SATCHEL_VAULT_PASSPHRASE")
    if stored is not None:
        return stored
    passphrase = getpass.getpass("Vault passphrase: ")
    if confirm and passphrase != getpass.getpass("Confirm passphrase: "):
        sys.exit("passphrases do not match")
    return passphrase


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(prog="satchel-vault", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p_setup = sub.add_parser("setup", help="generate a seed from dice rolls")
    p_setup.add_argument("--dice", required=True, help="at least 50 rolls (128 bits), digits 1-6")
    p_setup.add_argument(
        "--ledger-address",
        required=True,
        help="Ethereum address of the approval Ledger (0x + 40 hex)",
    )
    p_reset = sub.add_parser("reset", help="wipe seed and inventory")
    p_reset.add_argument("--yes", action="store_true")
    p_serve = sub.add_parser("serve", help="serve the payload API")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=8001)
    args = parser.parse_args(argv)

    vault = Vault.from_env()
    if args.command == "setup":
        fingerprint = vault.setup(
            args.dice, _passphrase(confirm=True), args.ledger_address
        )
        print(f"seed created; fingerprint {fingerprint}")
    elif args.command == "reset":
        if not args.yes:
            sys.exit("refusing to reset without --yes")
        vault.reset()
        print("vault reset")
    elif args.command == "serve":
        import uvicorn

        uvicorn.run(
            "satchel_vault.app:create_app_from_env",
            factory=True,
            host=args.host,
            port=args.port,
        )
