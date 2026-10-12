"""Fund allocated envelopes on regtest."""

from satchel_core.events import emit
from satchel_core.payloads import MessageType
from satchel_core.regtest import COIN, RegtestNode, btc_to_sats

from .state import LaptopState
from .vault_client import VaultClient

MARGIN_SATS = COIN


def fund_envelopes(
    vault_client: VaultClient, node: RegtestNode, state: LaptopState
) -> list[dict]:
    # In the real design envelopes are funded through the approved large-spend
    # flow (vault plan, Ledger approval, signer), not from the regtest faucet.
    payload = vault_client.fetch_envelopes()
    if (
        payload.type != MessageType.ADDRESS_EXPORT
        or payload.body.get("kind") != "envelope"
    ):
        raise ValueError("expected an envelope address_export payload")
    entries = payload.body.get("addresses") or []
    node.ensure_faucet(sum(e["budget_sats"] for e in entries) + MARGIN_SATS)
    pending = []
    for entry in entries:
        if state.funding_for(entry["address"]):
            continue
        txid = node.send_to_address(entry["address"], entry["budget_sats"])
        pending.append((entry, txid))
    if not pending:
        return []
    node.mine_blocks(1, node.faucet_address())
    funded = []
    for entry, txid in pending:
        tx = node.get_transaction(txid)
        vout = None
        for v in tx["vout"]:
            if (
                v["scriptPubKey"].get("address") == entry["address"]
                and btc_to_sats(v["value"]) == entry["budget_sats"]
            ):
                vout = v["n"]
                break
        if vout is None:
            raise RuntimeError(
                f"tx {txid} has no output paying "
                f"{entry['budget_sats']} sats to {entry['address']}"
            )
        state.record_funding(entry["address"], txid, vout, entry["budget_sats"])
        funded.append(
            {
                "index": entry["index"],
                "address": entry["address"],
                "txid": txid,
                "vout": vout,
                "amount_sats": entry["budget_sats"],
            }
        )
        emit(
            "laptop",
            "envelope_funded",
            f"funded envelope {entry['index']} with {entry['budget_sats']} sats",
            {"txid": txid, "vout": vout, "amount_sats": entry["budget_sats"]},
        )
    return funded
