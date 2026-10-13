"""Envelope status derived from chain data overlaid on the vault export."""

from dataclasses import dataclass

from embit import ec, script

from satchel_core.keys import NETWORK
from satchel_core.payloads import MessageType, Payload
from satchel_core.regtest import RegtestNode, Utxo

from .state import LaptopState


@dataclass
class EnvelopeStatus:
    index: int
    address: str
    budget_sats: int
    assigned_to: str | None
    status: str
    balance_sats: int
    available_sats: int
    utxo_count: int


def envelope_statuses(
    payload: Payload, node: RegtestNode, state: LaptopState
) -> list[EnvelopeStatus]:
    """Overlay confirmed chain state on an envelope address export."""
    if (
        payload.type != MessageType.ADDRESS_EXPORT
        or payload.body.get("kind") != "envelope"
    ):
        raise ValueError("expected an envelope address_export payload")
    entries = payload.body.get("addresses") or []
    for entry in entries:
        try:
            public_key = ec.PublicKey.parse(bytes.fromhex(entry["public_key"]))
        except (ValueError, KeyError) as exc:
            raise ValueError(f"bad envelope entry: {entry!r}") from exc
        if script.p2wpkh(public_key).address(NETWORK) != entry.get("address"):
            raise ValueError(
                f"envelope {entry.get('index')}: public_key does not match address"
            )
    utxos_by_address: dict[str, list[Utxo]] = {}
    for utxo in node.list_unspent([e["address"] for e in entries]):
        utxos_by_address.setdefault(utxo.address, []).append(utxo)
    statuses = []
    for entry in entries:
        address = entry["address"]
        utxos = utxos_by_address.get(address, [])
        balance = sum(u.amount_sats for u in utxos)
        available = sum(
            u.amount_sats
            for u in utxos
            if node.is_unspent(u.txid, u.vout, include_mempool=True)
        )
        on_chain = {(u.txid, u.vout) for u in utxos}
        missing = [
            (f["txid"], f["vout"])
            for f in state.funding_for(address)
            if (f["txid"], f["vout"]) not in on_chain
        ]
        if not state.funding_for(address) and balance == 0:
            status = "unfunded"
        elif balance == 0:
            status = "drained"
        elif missing:
            status = "spent"
        elif entry.get("assigned_to"):
            status = "assigned"
        else:
            status = "unassigned"
        statuses.append(
            EnvelopeStatus(
                index=entry["index"],
                address=address,
                budget_sats=entry["budget_sats"],
                assigned_to=entry.get("assigned_to"),
                status=status,
                balance_sats=balance,
                available_sats=available,
                utxo_count=len(utxos),
            )
        )
    return statuses
