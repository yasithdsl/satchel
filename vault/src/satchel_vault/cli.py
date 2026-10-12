"""Operator console for the air-gapped vault device."""

import argparse
import getpass
import json
import os
import sys

from satchel_core.payloads import to_http

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
    p_setup.add_argument("--dice", required=True, help="at least 20 rolls, digits 1-6")
    p_setup.add_argument(
        "--ledger-address",
        required=True,
        help="Ethereum address of the approval Ledger (0x + 40 hex)",
    )
    p_reset = sub.add_parser("reset", help="wipe seed and inventory")
    p_reset.add_argument("--yes", action="store_true")
    p_alloc = sub.add_parser("allocate", help="allocate prepaid envelopes")
    p_alloc.add_argument("--count", type=int)
    p_alloc.add_argument("--budget", type=int)
    p_alloc.add_argument(
        "--demo",
        action="store_true",
        help="allocate the demo envelope sizes",
    )
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
    elif args.command == "allocate":
        if args.demo:
            if args.budget is not None:
                parser.error("--demo cannot be combined with --budget")
            vault.unlock(_passphrase())
            count = args.count if args.count is not None else 1
            print(json.dumps(to_http(vault.allocate_demo_envelopes(count))))
        else:
            if args.count is None or args.budget is None:
                parser.error(
                    "allocate requires --count and --budget, or --demo"
                )
            vault.unlock(_passphrase())
            print(
                json.dumps(
                    to_http(
                        vault.allocate_envelopes(args.count, args.budget)
                    )
                )
            )
    elif args.command == "serve":
        import uvicorn

        uvicorn.run(
            "satchel_vault.app:create_app_from_env",
            factory=True,
            host=args.host,
            port=args.port,
        )
