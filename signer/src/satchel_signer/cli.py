"""Operator console for the air-gapped signer device."""

import argparse


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(
        prog="satchel-signer", description=__doc__
    )
    sub = parser.add_subparsers(dest="command", required=True)
    p_serve = sub.add_parser("serve", help="serve the signing API")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=8002)
    args = parser.parse_args(argv)

    if args.command == "serve":
        import uvicorn

        uvicorn.run(
            "satchel_signer.app:create_app_from_env",
            factory=True,
            host=args.host,
            port=args.port,
        )
