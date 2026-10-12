"""Fund any unfunded envelopes from the regtest faucet."""

import sys

import httpx

from satchel_core.regtest import NodeUnavailable, RegtestNode
from satchel_laptop.funding import fund_envelopes
from satchel_laptop.state import LaptopState
from satchel_laptop.vault_client import VaultClient


def main() -> None:
    try:
        funded = fund_envelopes(
            VaultClient(), RegtestNode.from_env(), LaptopState.from_env()
        )
    except NodeUnavailable:
        sys.exit("bitcoind is not running; start it with `uv run scripts/regtest.py up`")
    except httpx.HTTPError as exc:
        sys.exit(f"vault not reachable ({exc}); is `satchel-vault serve` running?")
    if not funded:
        print("nothing to fund")
    for entry in funded:
        print(
            f"funded envelope {entry['index']} ({entry['address']}): "
            f"{entry['amount_sats']} sats in {entry['txid']}:{entry['vout']}"
        )


if __name__ == "__main__":
    main()
