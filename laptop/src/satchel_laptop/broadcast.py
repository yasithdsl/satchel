"""Broadcast only transactions whose signatures the vault has verified."""

from embit.transaction import Transaction

from satchel_core.payloads import MessageType, Payload
from satchel_core.transactions import wtxid


class NotVerified(RuntimeError):
    pass


def broadcast_verified(node, signed_tx: Payload, verification: Payload) -> str:
    """Broadcast `signed_tx` only when `verification` passes for exactly it."""
    if verification.type != MessageType.VERIFICATION_RESULT:
        raise NotVerified("verification payload is not a verification_result")
    body = verification.body
    if body.get("result") != "pass":
        raise NotVerified("vault verification did not pass")
    if body.get("failures"):
        raise NotVerified("vault verification reported failures")
    if signed_tx.type != MessageType.SIGNED_TX:
        raise NotVerified("signed payload is not a signed_tx")
    tx_hex = signed_tx.body.get("tx")
    if not isinstance(tx_hex, str):
        raise NotVerified("signed_tx body has no 'tx' hex string")
    try:
        txid = Transaction.parse(bytes.fromhex(tx_hex)).txid().hex()
        checked_wtxid = wtxid(tx_hex)
    except Exception as exc:
        raise NotVerified("signed transaction does not parse") from exc
    if txid != body.get("txid"):
        raise NotVerified("signed tx txid does not match the verification")
    if checked_wtxid != body.get("wtxid"):
        raise NotVerified("signed tx wtxid does not match the verification")
    returned = node.broadcast(tx_hex)
    if returned != txid:
        raise RuntimeError(
            f"node returned txid {returned} for transaction {txid}"
        )
    return returned
