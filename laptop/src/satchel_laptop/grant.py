"""Envelope grant flow: plan -> Ledger approval -> vault key release -> agent."""

import re
import time
from dataclasses import dataclass

from satchel_agent.wallet import EnvelopeWallet
from satchel_core.payloads import MessageType, Payload

from .approver_client import ApproverClient
from .envelopes import envelope_statuses
from .flows import FlowRecorder
from .state import LaptopState
from .vault_client import VaultClient, VaultRefused

NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._-]{0,31}$")


@dataclass
class GrantResult:
    granted: bool
    flow_id: str
    envelope_index: int | None
    budget_sats: int
    wallet: EnvelopeWallet | None
    reason: str | None
    key_release: Payload | None = None


def grant_envelope(
    agent_id: str,
    budget_sats: int,
    *,
    vault: VaultClient,
    approver: ApproverClient,
    node,
    state: LaptopState,
    ttl_seconds: int = 3600,
    demo_auto: str | None = None,
    flows_dir=None,
    now: int | None = None,
) -> GrantResult:
    """Run the full envelope-grant flow; never raises for policy refusals."""
    if not isinstance(agent_id, str) or not NAME_RE.fullmatch(agent_id):
        raise ValueError(f"invalid agent_id: {agent_id!r}")
    if (
        isinstance(budget_sats, bool)
        or not isinstance(budget_sats, int)
        or budget_sats <= 0
    ):
        raise ValueError("budget_sats must be a positive integer")
    now = int(time.time()) if now is None else now
    flow = FlowRecorder("grant", flows_dir)

    def refused(reason: str) -> GrantResult:
        flow.finish("failed", {"reason": reason})
        return GrantResult(
            granted=False,
            flow_id=flow.flow_id,
            envelope_index=None,
            budget_sats=budget_sats,
            wallet=None,
            reason=reason,
        )

    stage = "fetch"
    try:
        export = vault.fetch_envelopes()
        flow.hop("envelopes_fetched", "vault", "laptop", export)
        statuses = envelope_statuses(export, node, state)
        candidates = [
            s
            for s in statuses
            if s.status == "unassigned" and s.budget_sats >= budget_sats
        ]
        if not candidates:
            return refused(
                f"no unassigned funded envelope with at least {budget_sats} sats"
            )
        chosen = min(candidates, key=lambda s: (s.budget_sats, s.index))
        expires_at = (now + ttl_seconds + 59) // 60 * 60
        plan = {
            "kind": "envelope_grant",
            "envelope_index": chosen.index,
            "agent_id": agent_id,
            "budget_sats": chosen.budget_sats,
            "expires_at": expires_at,
        }
        flow.hop(
            "plan_sent_to_approver",
            "laptop",
            "approver",
            Payload(MessageType.SPEND_PLAN, {"plan": plan}),
        )
        stage = "approval"
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
            return refused("rejected on the Ledger")
        flow.hop("approval_received", "approver", "laptop", outcome.payload)
        flow.hop("approval_sent_to_vault", "laptop", "vault", outcome.payload)
        stage = "release"
        try:
            release = vault.release_envelope(outcome.payload)
        except VaultRefused as exc:
            return refused(exc.reason)
        flow.hop("key_release_received", "vault", "laptop", release)
        stage = "deliver"
        wallet = EnvelopeWallet.from_key_release(release, node)
        flow.hop(
            "key_delivered_to_agent",
            "laptop",
            f"agent:{agent_id}",
            release,
        )
        result = {
            "envelope_index": chosen.index,
            "agent_id": agent_id,
            "budget_sats": chosen.budget_sats,
            "address": wallet.address,
        }
        flow.finish("completed", result)
        return GrantResult(
            granted=True,
            flow_id=flow.flow_id,
            envelope_index=chosen.index,
            budget_sats=chosen.budget_sats,
            wallet=wallet,
            reason=None,
            key_release=release,
        )
    except Exception as exc:
        flow.finish("failed", {"stage": stage, "error": str(exc)})
        raise
