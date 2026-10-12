"""Large-spend flow: coin selection -> Ledger approval -> release -> sign ->
vault verify -> broadcast."""

import base64
import hashlib
import math
import re
from dataclasses import dataclass, field

from embit import script

from satchel_core.payloads import MessageType, Payload
from satchel_core.transactions import (
    DUST_LIMIT_SATS,
    Output,
    SpendInput,
    build_psbt,
    estimate_vsize,
)

from .approver_client import ApproverClient
from .broadcast import broadcast_verified
from .flows import FlowRecorder
from .signer_client import SignerClient
from .state import LaptopState
from .vault_client import VaultClient, VaultRefused

NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._-]{0,31}$")
DEST_RE = re.compile(r"^bcrt1[02-9ac-hj-np-z]{8,87}$")


@dataclass
class SpendResult:
    broadcast: bool
    flow_id: str
    txid: str | None
    stage: str
    reason: str | None
    failures: list = field(default_factory=list)


def _check_destination(destination: str) -> None:
    if not isinstance(destination, str) or not DEST_RE.fullmatch(destination):
        raise ValueError(f"destination must be a regtest bcrt1 address: {destination!r}")
    try:
        script.address_to_scriptpubkey(destination)
    except ValueError as exc:
        raise ValueError(f"invalid destination address: {destination!r}") from exc


def large_spend(
    destination: str,
    amount_sats: int,
    purpose: str,
    *,
    vault: VaultClient,
    approver: ApproverClient,
    signer: SignerClient,
    node,
    state: LaptopState,
    fee_rate_sat_vb: float = 2,
    demo_auto: str | None = None,
    flows_dir=None,
) -> SpendResult:
    """Run the large-spend flow; policy refusals return a SpendResult."""
    _check_destination(destination)
    if (
        isinstance(amount_sats, bool)
        or not isinstance(amount_sats, int)
        or amount_sats < DUST_LIMIT_SATS
    ):
        raise ValueError(
            f"amount_sats must be an integer >= {DUST_LIMIT_SATS}"
        )
    if not isinstance(purpose, str) or not NAME_RE.fullmatch(purpose):
        raise ValueError(f"invalid purpose: {purpose!r}")

    flow = FlowRecorder("spend", flows_dir)

    def stopped(stage: str, reason: str, failures: list | None = None) -> SpendResult:
        flow.finish("failed", {"stage": stage, "reason": reason})
        return SpendResult(
            broadcast=False,
            flow_id=flow.flow_id,
            txid=None,
            stage=stage,
            reason=reason,
            failures=failures or [],
        )

    stage = "change"
    try:
        change_payload = vault.export_change(1)
        flow.hop("change_address_exported", "vault", "laptop", change_payload)
        change_entries = change_payload.body.get("addresses") or []
        if not change_entries:
            raise ValueError("vault exported no change address")
        change_entry = change_entries[0]
        state.add_main_funds(
            change_payload.body["fingerprint"],
            [{"kind": "change", **change_entry}],
        )

        stage = "select"
        funds = state.main_funds
        entries = funds["addresses"]
        entry_by_address = {e["address"]: e for e in entries}
        available = [
            u
            for u in node.list_unspent([e["address"] for e in entries])
            if node.is_unspent(u.txid, u.vout, include_mempool=True)
            and u.address in entry_by_address
        ]
        available.sort(key=lambda u: (-u.amount_sats, u.txid, u.vout))
        selected = []
        total = 0
        fee_sats = change_sats = None
        for utxo in available:
            selected.append(utxo)
            total += utxo.amount_sats
            vsize = estimate_vsize(
                len(selected), [destination, change_entry["address"]]
            )
            fee_with_change = math.ceil(vsize * fee_rate_sat_vb)
            if total < amount_sats + fee_with_change:
                continue
            change_amount = total - amount_sats - fee_with_change
            if change_amount >= DUST_LIMIT_SATS:
                fee_sats, change_sats = fee_with_change, change_amount
            else:
                change_sats = None
                fee_sats = total - amount_sats
            break
        if fee_sats is None:
            needed = amount_sats + math.ceil(
                estimate_vsize(
                    max(len(selected), 1),
                    [destination, change_entry["address"]],
                )
                * fee_rate_sat_vb
            )
            return stopped(
                "select",
                f"insufficient funds: need about {needed} sats, have {total}",
            )
        flow.hop(
            "utxos_selected",
            "laptop",
            "laptop",
            None,
            {
                "outpoints": [
                    {
                        "txid": u.txid,
                        "vout": u.vout,
                        "amount_sats": u.amount_sats,
                        "path": entry_by_address[u.address]["path"],
                    }
                    for u in selected
                ],
                "total_sats": total,
                "fee_sats": fee_sats,
                "change_sats": change_sats,
            },
        )

        stage = "build"
        inputs = [
            SpendInput(
                u.txid,
                u.vout,
                u.amount_sats,
                entry_by_address[u.address]["public_key"],
                entry_by_address[u.address]["path"],
            )
            for u in selected
        ]
        change = (
            Output(
                change_entry["address"],
                change_sats,
                change_entry["path"],
                change_entry["public_key"],
            )
            if change_sats is not None
            else None
        )
        psbt = build_psbt(
            inputs,
            [Output(destination, amount_sats)],
            change,
            fingerprint=funds["fingerprint"],
        )
        raw = psbt.serialize()
        psbt_payload = Payload(
            MessageType.UNSIGNED_PSBT, {"psbt": base64.b64encode(raw).decode()}
        )
        flow.hop("psbt_built", "laptop", "laptop", psbt_payload)

        stage = "approval"
        plan = {
            "kind": "large_spend",
            "amount_sats": amount_sats,
            "destination": destination,
            "purpose": purpose,
            "psbt_sha256": hashlib.sha256(raw).hexdigest(),
        }
        flow.hop(
            "plan_sent_to_approver",
            "laptop",
            "approver",
            Payload(MessageType.SPEND_PLAN, {"plan": plan}),
        )
        outcome = approver.approve(plan, demo_auto)
        if not outcome.approved:
            flow.hop(
                "approval_rejected",
                "approver",
                "laptop",
                None,
                {
                    "reason": outcome.reason,
                    "nonce": outcome.nonce,
                    "text": outcome.text,
                },
            )
            return stopped("approval", "rejected on the Ledger")
        flow.hop("approval_received", "approver", "laptop", outcome.payload)
        flow.hop("approval_sent_to_vault", "laptop", "vault", outcome.payload)

        stage = "release"
        try:
            keys = vault.release_spend(outcome.payload, psbt_payload)
        except VaultRefused as exc:
            return stopped("release", exc.reason)
        flow.hop("keys_released", "vault", "laptop", keys)
        flow.hop("keys_sent_to_signer", "laptop", "signer", keys)

        stage = "sign"
        signed = signer.request_signature(psbt_payload, keys)
        flow.hop("signed_tx_received", "signer", "laptop", signed)

        stage = "verify"
        verification = vault.verify(psbt_payload, signed)
        flow.hop("verification_received", "vault", "laptop", verification)
        body = verification.body
        if body.get("result") == "pass" and not body.get("failures"):
            stage = "broadcast"
            txid = broadcast_verified(node, signed, verification)
            flow.hop("broadcast", "laptop", "node", signed, {"txid": txid})
            flow.finish("completed", {"txid": txid})
            return SpendResult(
                broadcast=True,
                flow_id=flow.flow_id,
                txid=txid,
                stage="broadcast",
                reason=None,
                failures=[],
            )
        failures = body.get("failures") or []
        reason = (
            "; ".join(f["reason"] for f in failures) or "verification failed"
        )
        return stopped("verification", reason, failures)
    except Exception as exc:
        flow.finish("failed", {"stage": stage, "error": str(exc)})
        raise
