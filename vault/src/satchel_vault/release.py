"""Key release: the only vault module besides verification that reads WIFs."""

from datetime import datetime, timezone

from satchel_core.keys import MasterKey
from satchel_core.payloads import MessageType, Payload
from satchel_core.transactions import input_derivation

from .approvals import validate_approval
from .inventory import Inventory


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def release_envelope(
    master: MasterKey,
    inventory: Inventory,
    ledger_address: str,
    approval: Payload,
) -> tuple[Payload, dict]:
    """Validate a grant approval, assign the envelope, and release its key."""
    plan, _ = validate_approval(
        approval,
        master=master,
        ledger_address=ledger_address,
        inventory=inventory,
    )
    index = plan["envelope_index"]
    key = master.envelope(index)
    inventory.envelopes[index].update(
        {
            "assigned_to": plan["agent_id"],
            "assigned_at": _now(),
            "expires_at": plan["expires_at"],
        }
    )
    inventory.data["used_nonces"].append(approval.body["nonce"])
    inventory.save()
    return (
        Payload(
            MessageType.KEY_RELEASE,
            {
                "kind": "envelope",
                "envelope_index": index,
                "path": key.path,
                "address": key.address,
                "public_key": key.public_key,
                "wif": key.wif,
                "budget_sats": plan["budget_sats"],
                "agent_id": plan["agent_id"],
                "expires_at": plan["expires_at"],
            },
        ),
        plan,
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
    keys = []
    seen = set()
    for i in range(len(psbt.inputs)):
        derivation = input_derivation(psbt, i)
        path = derivation[2]
        if path in seen:
            continue
        seen.add(path)
        keys.append({"path": path, "wif": master.derive(path).wif})
    inventory.data["used_nonces"].append(approval.body["nonce"])
    inventory.save()
    return (
        Payload(
            MessageType.KEY_RELEASE,
            {"kind": "signing", "keys": keys},
        ),
        plan,
    )
