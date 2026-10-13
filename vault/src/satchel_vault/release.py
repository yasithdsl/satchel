"""Key release: the only vault module besides verification that reads WIFs."""

import time
from datetime import datetime, timezone

from satchel_core.keys import MasterKey
from satchel_core.payloads import MessageType, Payload
from satchel_core.transactions import input_derivation

from .approvals import ApprovalRejected, EnvelopeUnavailable, validate_approval
from .confirmation import InvalidProof, verify_txout_proof
from .inventory import Inventory


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _signing_keys(master: MasterKey, psbt) -> list[dict]:
    """One WIF per distinct main-funds input key, nothing else."""
    keys = []
    seen = set()
    for i in range(len(psbt.inputs)):
        path = input_derivation(psbt, i)[2]
        if path in seen:
            continue
        seen.add(path)
        keys.append({"path": path, "wif": master.derive(path).wif})
    return keys


def release_satchel_funding(
    master: MasterKey,
    inventory: Inventory,
    ledger_address: str,
    approval: Payload,
    unsigned_psbt: bytes,
) -> tuple[Payload, dict]:
    """Validate a satchel grant and release the main-fund keys that fund it.

    The satchel's own key stays in the vault until the funding is verified
    and confirmed (release_satchel).
    """
    plan, psbt = validate_approval(
        approval,
        master=master,
        ledger_address=ledger_address,
        inventory=inventory,
        unsigned_psbt=unsigned_psbt,
    )
    if plan["kind"] != "satchel_grant":
        raise ApprovalRejected("approval is not a satchel grant")
    keys = _signing_keys(master, psbt)
    inventory.envelopes[plan["satchel_index"]].update(
        {
            "status": "funding",
            "agent_id": plan["agent_id"],
            "expires_at": plan["expires_at"],
            "psbt_sha256": plan["psbt_sha256"],
            "approval_nonce": approval.body["nonce"],
            "approved_at": _now(),
        }
    )
    inventory.data["used_nonces"].append(approval.body["nonce"])
    inventory.save()
    return (
        Payload(MessageType.KEY_RELEASE, {"kind": "signing", "keys": keys}),
        plan,
    )


def release_satchel(
    master: MasterKey,
    inventory: Inventory,
    proof: Payload,
    now: int | None = None,
) -> Payload:
    """Hand the satchel key to its agent once its funding is confirmed.

    The funding must be the exact transaction the vault verified for this
    satchel, and the proof must show it in a block with valid work.
    """
    now = int(time.time()) if now is None else now
    if proof.type != MessageType.FUNDING_PROOF:
        raise ApprovalRejected("payload is not a funding_proof")
    body = proof.body
    if set(body) != {"satchel_index", "txid", "proof"}:
        raise ApprovalRejected("funding proof has missing or extra keys")
    index = body["satchel_index"]
    if (
        not isinstance(index, int)
        or isinstance(index, bool)
        or not 0 <= index < len(inventory.envelopes)
    ):
        raise ApprovalRejected("unknown satchel")
    satchel = inventory.envelopes[index]
    if satchel.get("status") == "assigned":
        raise EnvelopeUnavailable("satchel key was already released")
    if satchel.get("status") != "verified":
        raise ApprovalRejected("satchel funding has not passed verification")
    if body["txid"] != satchel.get("funding_txid"):
        raise ApprovalRejected(
            "proof is for a different transaction than the verified funding"
        )
    try:
        confirmed = verify_txout_proof(body["proof"], body["txid"])
    except InvalidProof as exc:
        raise ApprovalRejected(f"funding is not confirmed: {exc}") from exc
    if satchel["expires_at"] <= now:
        raise ApprovalRejected("satchel grant has expired")
    key = master.envelope(index)
    if key.address != satchel["address"]:
        raise ApprovalRejected("satchel address does not match its key")
    satchel.update(
        {
            "status": "assigned",
            "assigned_to": satchel["agent_id"],
            "assigned_at": _now(),
            "funding_block": confirmed["block_hash"],
        }
    )
    inventory.save()
    return Payload(
        MessageType.KEY_RELEASE,
        {
            "kind": "envelope",
            "envelope_index": index,
            "path": key.path,
            "address": key.address,
            "public_key": key.public_key,
            "wif": key.wif,
            "budget_sats": satchel["budget_sats"],
            "agent_id": satchel["agent_id"],
            "expires_at": satchel["expires_at"],
        },
    )


def release_spend(
    master: MasterKey,
    inventory: Inventory,
    ledger_address: str,
    approval: Payload,
    unsigned_psbt: bytes,
) -> tuple[Payload, dict]:
    """Validate a spend approval and release one WIF per distinct input key."""
    plan, psbt = validate_approval(
        approval,
        master=master,
        ledger_address=ledger_address,
        inventory=inventory,
        unsigned_psbt=unsigned_psbt,
    )
    if plan["kind"] != "large_spend":
        raise ApprovalRejected("approval is not a large spend")
    keys = _signing_keys(master, psbt)
    inventory.data["used_nonces"].append(approval.body["nonce"])
    inventory.save()
    return (
        Payload(
            MessageType.KEY_RELEASE,
            {"kind": "signing", "keys": keys},
        ),
        plan,
    )
