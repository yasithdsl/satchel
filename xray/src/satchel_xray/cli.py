"""Serve the x-ray API."""

import argparse

import uvicorn


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(
        prog="satchel-xray", description=__doc__
    )
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve", help="serve the x-ray API")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8006)
    args = parser.parse_args(argv)
    if args.command == "serve":
        uvicorn.run(
            "satchel_xray.app:create_app_from_env",
            factory=True,
            host=args.host,
            port=args.port,
        )
