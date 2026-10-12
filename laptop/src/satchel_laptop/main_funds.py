"""Export the vault's main-funds addresses and fund them on regtest."""

from satchel_core.events import emit
from satchel_core.payloads import MessageType
from satchel_core.regtest import COIN, RegtestNode, btc_to_sats

from .flows import FlowRecorder
from .state import LaptopState
from .vault_client import VaultClient

DEFAULT_AMOUNTS = (50_000_000, 30_000_000, 20_000_000)


def fund_main_funds(
    vault: VaultClient,
    node: RegtestNode,
    state: LaptopState,
    amounts_sats: tuple[int, ...] = DEFAULT_AMOUNTS,
    flows_dir=None,
) -> list[dict]:
    """Export receive addresses, fund each from the faucet, mine one block."""
    flow = FlowRecorder("setup", flows_dir)
    payload = vault.export_receive(len(amounts_sats))
    if (
        payload.type != MessageType.ADDRESS_EXPORT
        or payload.body.get("kind") != "receive"
    ):
        raise ValueError("expected a receive address_export payload")
    entries = payload.body.get("addresses") or []
    if len(entries) != len(amounts_sats):
        raise ValueError(
            f"vault exported {len(entries)} addresses, "
            f"expected {len(amounts_sats)}"
        )
    flow.hop("receive_addresses_exported", "vault", "laptop", payload)
    state.add_main_funds(
        payload.body["fingerprint"],
        [{"kind": "receive", **e} for e in entries],
    )
    node.ensure_faucet(sum(amounts_sats) + COIN)
    pending = []
    for entry, amount in zip(entries, amounts_sats):
        txid = node.send_to_address(entry["address"], amount)
        pending.append((entry, amount, txid))
    node.mine_blocks(1, node.faucet_address())
    funded = []
    for entry, amount, txid in pending:
        tx = node.get_transaction(txid)
        vout = None
        for v in tx["vout"]:
            if (
                v["scriptPubKey"].get("address") == entry["address"]
                and btc_to_sats(v["value"]) == amount
            ):
                vout = v["n"]
                break
        if vout is None:
            raise RuntimeError(
                f"tx {txid} has no output paying {amount} sats "
                f"to {entry['address']}"
            )
        state.record_funding(entry["address"], txid, vout, amount)
        record = {
            "index": entry["index"],
            "address": entry["address"],
            "txid": txid,
            "vout": vout,
            "amount_sats": amount,
        }
        funded.append(record)
        emit(
            "laptop",
            "main_fund_funded",
            f"funded main-funds address {entry['index']} with {amount} sats",
            record,
        )
    flow.hop(
        "main_funds_funded",
        "faucet",
        "vault",
        None,
        {"funded": funded},
    )
    flow.finish("completed", {"funded": funded})
    return funded
