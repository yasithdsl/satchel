"""Manage the local regtest bitcoind (see docker-compose.yml)."""

import argparse
import subprocess
import sys
from pathlib import Path

from satchel_core.regtest import NodeUnavailable, RegtestNode, sats_to_btc

COMPOSE_FILE = Path(__file__).resolve().parents[1] / "docker-compose.yml"


def compose(*args: str) -> None:
    try:
        subprocess.run(
            ["docker", "compose", "-f", str(COMPOSE_FILE), *args], check=True
        )
    except FileNotFoundError:
        sys.exit("docker not found; install Docker Desktop and retry")
    except subprocess.CalledProcessError as exc:
        sys.exit(f"docker compose failed with exit code {exc.returncode}")


def node_or_exit(check_faucet: bool = False) -> RegtestNode:
    node = RegtestNode.from_env()
    try:
        if check_faucet:
            node.ensure_faucet()
        else:
            node.call("getblockchaininfo")
    except NodeUnavailable:
        sys.exit("bitcoind is not running; start it with `uv run scripts/regtest.py up`")
    return node


def cmd_up(_args) -> None:
    compose("up", "-d", "--wait", "--wait-timeout", "120")
    node = node_or_exit(check_faucet=True)
    height = node.call("getblockchaininfo")["blocks"]
    print(f"RPC: {node.url}")
    print(f"block height: {height}")
    print(f"faucet balance: {sats_to_btc(node.faucet_balance_sats())} BTC")


def cmd_down(_args) -> None:
    compose("down")


def cmd_fund(args) -> None:
    node = node_or_exit(check_faucet=True)
    txid = node.fund_address(args.address, args.sats)
    print(f"sent {args.sats} sats to {args.address}")
    print(f"txid: {txid}")
    print("confirmed in a block")


def cmd_unspent(args) -> None:
    node = node_or_exit()
    utxos = node.list_unspent(args.addresses)
    total = 0
    for utxo in utxos:
        total += utxo.amount_sats
        print(f"{utxo.txid}:{utxo.vout}  {utxo.amount_sats} sats  height {utxo.height}")
    print(f"total: {total} sats")


def cmd_miner(args) -> None:
    import time

    node = node_or_exit(check_faucet=True)
    print(f"mining a block every {args.interval} s; Ctrl-C to stop")
    try:
        while True:
            block = node.mine_blocks(1, node.faucet_address())[0]
            print(f"mined {block}")
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("miner stopped")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("up", help="start bitcoind and make sure the faucet has funds")
    sub.add_parser("down", help="stop bitcoind (keeps the chain volume)")
    fund = sub.add_parser("fund", help="send sats to an address and confirm them")
    fund.add_argument("address")
    fund.add_argument("sats", type=int, nargs="?", default=1_000_000)
    unspent = sub.add_parser("unspent", help="list confirmed UTXOs for addresses")
    unspent.add_argument("addresses", nargs="+")
    miner = sub.add_parser("miner", help="mine a block every N seconds until Ctrl-C")
    miner.add_argument("--interval", type=float, default=10)
    args = parser.parse_args()
    {
        "up": cmd_up,
        "down": cmd_down,
        "fund": cmd_fund,
        "unspent": cmd_unspent,
        "miner": cmd_miner,
    }[args.command](args)


if __name__ == "__main__":
    main()
