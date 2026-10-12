"""Operator console for the laptop coordinator."""

import argparse

import uvicorn


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(prog="satchel-laptop", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve", help="serve the coordinator API")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    args = parser.parse_args(argv)
    if args.command == "serve":
        uvicorn.run(
            "satchel_laptop.app:create_app_from_env",
            factory=True,
            host=args.host,
            port=args.port,
        )
