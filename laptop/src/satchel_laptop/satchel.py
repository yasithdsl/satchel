"""Satchel flow: one Ledger approval funds a fresh satchel from main funds and
hands its key to the agent.

vault reserves a fresh hardened satchel key -> laptop drafts a main-funds PSBT
paying exactly the budget to it -> Ledger approves the plan -> vault checks the
approval and the PSBT and releases only the main-fund keys -> signer signs ->
vault verifies byte for byte -> broadcast -> confirmed in a block -> vault
checks the confirmation proof and releases the satchel key -> agent.
"""

import hashlib
import re
import time
from dataclasses import dataclass

from embit import script
from embit.psbt import PSBT

from satchel_core.keys import HARDENED, Branch, parse_hardened_path
from satchel_core.payloads import MessageType, Payload
from satchel_core.regtest import RPCError

from .approver_client import ApproverClient
from .flows import FlowRecorder
from .signer_client import SignerClient
from .spend import (
    Stopped,
    approve_on_ledger,
    build_main_funds_psbt,
    sign_verify_broadcast,
)
from .state import LaptopState
from .vault_client import VaultClient, VaultRefused

NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._-]{0,31}$")


@dataclass
class GrantResult:
    granted: bool
    flow_id: str
    envelope_index: int | None
    budget_sats: int
    reason: str | None
    stage: str | None = None
    key_release: Payload | None = None


def _satchel_vout(raw_psbt: bytes, address: str) -> int:
    target = script.address_to_scriptpubkey(address)
    for i, out in enumerate(PSBT.parse(raw_psbt).tx.vout):
        if out.script_pubkey == target:
            return i
    raise ValueError("funding PSBT does not pay the satchel")


def wait_for_proof(
    node,
    txid: str,
    *,
    demo_mine: bool,
    timeout: float,
    poll_interval: float,
) -> str:
    """Return a `gettxoutproof` for txid once it is in a block.

    In demo mode a block is mined straight away instead of waiting.
    """
    if demo_mine:
        node.mine_blocks(1, node.faucet_address())
    deadline = time.monotonic() + timeout
    while True:
        try:
            return node.call("gettxoutproof", [txid])
        except RPCError:
            if time.monotonic() >= deadline:
                raise Stopped("confirm", "the funding did not confirm in time")
            time.sleep(poll_interval)


def create_satchel(
    agent_id: str,
    budget_sats: int,
    *,
    vault: VaultClient,
    approver: ApproverClient,
    signer: SignerClient,
    node,
    state: LaptopState,
    ttl_seconds: int = 3600,
    demo_auto: str | None = None,
    demo_mine: bool = False,
    confirm_timeout: float = 600.0,
    poll_interval: float = 1.0,
    fee_rate_sat_vb: float = 2,
    flows_dir=None,
    now: int | None = None,
) -> GrantResult:
    """Create, fund and hand over a satchel; never raises for policy refusals."""
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
    index: int | None = None

    def refused(stage: str, reason: str) -> GrantResult:
        flow.finish("failed", {"stage": stage, "reason": reason})
        return GrantResult(
            granted=False,
            flow_id=flow.flow_id,
            envelope_index=index,
            budget_sats=budget_sats,
            reason=reason,
            stage=stage,
        )

    try:
        flow.stage = "reserve"
        reservation = vault.reserve_satchel(budget_sats)
        entries = reservation.body.get("addresses") or []
        if (
            reservation.type != MessageType.ADDRESS_EXPORT
            or reservation.body.get("kind") != "envelope"
            or len(entries) != 1
        ):
            raise ValueError("vault did not reserve exactly one satchel")
        satchel = entries[0]
        index = satchel["index"]
        path = parse_hardened_path(satchel["path"])
        if (
            path[3] != Branch.ENVELOPE | HARDENED
            or path[4] != index | HARDENED
            or satchel["budget_sats"] != budget_sats
        ):
            raise ValueError("reserved satchel does not match the request")
        flow.hop("satchel_reserved", "vault", "laptop", reservation)

        psbt_payload, raw = build_main_funds_psbt(
            satchel["address"],
            budget_sats,
            vault=vault,
            node=node,
            state=state,
            flow=flow,
            fee_rate_sat_vb=fee_rate_sat_vb,
        )
        plan = {
            "kind": "satchel_grant",
            "satchel_index": index,
            "agent_id": agent_id,
            "budget_sats": budget_sats,
            "expires_at": (now + ttl_seconds + 59) // 60 * 60,
            "psbt_sha256": hashlib.sha256(raw).hexdigest(),
        }
        approval = approve_on_ledger(
            plan, approver=approver, flow=flow, demo_auto=demo_auto
        )

        flow.stage = "release"
        try:
            keys = vault.release_satchel_funding(approval, psbt_payload)
        except VaultRefused as exc:
            return refused("release", exc.reason)
        txid = sign_verify_broadcast(
            psbt_payload, keys, vault=vault, signer=signer, node=node, flow=flow
        )
        state.record_funding(
            satchel["address"], txid, _satchel_vout(raw, satchel["address"]), budget_sats
        )

        flow.stage = "confirm"
        proof = wait_for_proof(
            node,
            txid,
            demo_mine=demo_mine,
            timeout=confirm_timeout,
            poll_interval=poll_interval,
        )
        flow.hop("funding_confirmed", "node", "laptop", None, {"txid": txid})
        proof_payload = Payload(
            MessageType.FUNDING_PROOF,
            {"satchel_index": index, "txid": txid, "proof": proof},
        )
        flow.hop("funding_proof_sent", "laptop", "vault", proof_payload)

        flow.stage = "key"
        try:
            release = vault.release_satchel(proof_payload)
        except VaultRefused as exc:
            return refused("key", exc.reason)
        flow.hop("key_release_received", "vault", "laptop", release)
        if (
            release.type != MessageType.KEY_RELEASE
            or release.body.get("kind") != "envelope"
            or release.body.get("envelope_index") != index
            or release.body.get("agent_id") != agent_id
            or release.body.get("budget_sats") != budget_sats
            or release.body.get("address") != satchel["address"]
        ):
            return refused(
                "deliver", "vault key_release does not match the approved satchel"
            )
        flow.hop(
            "key_delivered_to_agent",
            "laptop",
            f"agent:{agent_id}",
            release,
        )
        flow.finish(
            "completed",
            {
                "envelope_index": index,
                "agent_id": agent_id,
                "budget_sats": budget_sats,
                "funding_txid": txid,
                "address": satchel["address"],
            },
        )
        return GrantResult(
            granted=True,
            flow_id=flow.flow_id,
            envelope_index=index,
            budget_sats=budget_sats,
            reason=None,
            stage="deliver",
            key_release=release,
        )
    except Stopped as stop:
        return refused(stop.stage, stop.reason)
    except Exception as exc:
        flow.finish("failed", {"stage": flow.stage, "error": str(exc)})
        raise
