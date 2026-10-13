"""HTTP surface of the laptop coordinator."""

import os
from dataclasses import asdict

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from satchel_core.payloads import to_http
from satchel_core.regtest import NodeUnavailable, RegtestNode

from .approver_client import ApproverClient, ApproverError
from .envelopes import envelope_statuses
from .satchel import create_satchel
from .signer_client import SignerClient
from .spend import large_spend
from .state import LaptopState
from .vault_client import VaultClient


class GrantRequest(BaseModel):
    agent_id: str
    budget_sats: int
    demo_auto: str | None = None


class SpendRequest(BaseModel):
    destination: str
    amount_sats: int
    purpose: str
    demo_auto: str | None = None


def create_app(
    vault_client: VaultClient,
    node: RegtestNode,
    state: LaptopState,
    approver: ApproverClient | None = None,
    signer: SignerClient | None = None,
    flows_dir=None,
    demo_mine: bool = False,
) -> FastAPI:
    app = FastAPI(title="satchel-laptop")

    @app.get("/health")
    def health():
        return {"ok": True}

    @app.get("/envelopes")
    def envelopes():
        try:
            payload = vault_client.fetch_envelopes()
        except (httpx.HTTPError, ValueError) as exc:
            raise HTTPException(502, f"vault request failed: {exc}")
        try:
            statuses = envelope_statuses(payload, node, state)
        except NodeUnavailable as exc:
            raise HTTPException(503, f"bitcoind unreachable: {exc}")
        return {"envelopes": [asdict(s) for s in statuses]}

    @app.get("/main-funds")
    def main_funds():
        funds = state.main_funds
        if not funds:
            return {
                "fingerprint": None,
                "addresses": 0,
                "utxos": 0,
                "balance_sats": 0,
                "available_sats": 0,
            }
        entries = funds["addresses"]
        try:
            utxos = node.list_unspent([e["address"] for e in entries])
            available = sum(
                u.amount_sats
                for u in utxos
                if node.is_unspent(u.txid, u.vout, include_mempool=True)
            )
        except NodeUnavailable as exc:
            raise HTTPException(503, f"bitcoind unreachable: {exc}")
        return {
            "fingerprint": funds["fingerprint"],
            "addresses": len(entries),
            "utxos": len(utxos),
            "balance_sats": sum(u.amount_sats for u in utxos),
            "available_sats": available,
        }

    @app.post("/grants")
    def grants(request: GrantRequest):
        """Create a satchel: one Ledger approval funds it from main funds."""
        if approver is None or signer is None:
            raise HTTPException(503, "approver/signer is not configured")
        try:
            result = create_satchel(
                request.agent_id,
                request.budget_sats,
                vault=vault_client,
                approver=approver,
                signer=signer,
                node=node,
                state=state,
                demo_auto=request.demo_auto,
                demo_mine=demo_mine,
                flows_dir=flows_dir,
            )
        except ApproverError as exc:
            raise HTTPException(503, f"approver request failed: {exc}")
        except ValueError as exc:
            raise HTTPException(422, str(exc))
        if not result.granted:
            return {
                "granted": False,
                "flow_id": result.flow_id,
                "stage": result.stage,
                "reason": result.reason,
            }
        return {
            "granted": True,
            "flow_id": result.flow_id,
            "envelope_index": result.envelope_index,
            "budget_sats": result.budget_sats,
            "key_release": to_http(result.key_release),
        }

    @app.post("/spends")
    def spends(request: SpendRequest):
        if approver is None or signer is None:
            raise HTTPException(503, "approver/signer is not configured")
        try:
            result = large_spend(
                request.destination,
                request.amount_sats,
                request.purpose,
                vault=vault_client,
                approver=approver,
                signer=signer,
                node=node,
                state=state,
                demo_auto=request.demo_auto,
                flows_dir=flows_dir,
            )
        except ApproverError as exc:
            raise HTTPException(503, f"approver request failed: {exc}")
        except ValueError as exc:
            raise HTTPException(422, str(exc))
        return {
            "broadcast": result.broadcast,
            "txid": result.txid,
            "stage": result.stage,
            "reason": result.reason,
            "failures": result.failures,
            "flow_id": result.flow_id,
        }

    return app


def create_app_from_env() -> FastAPI:
    return create_app(
        VaultClient(),
        RegtestNode.from_env(),
        LaptopState.from_env(),
        approver=ApproverClient(),
        signer=SignerClient(),
        # DEMO ONLY: mine a block as soon as a satchel's funding is broadcast.
        demo_mine=os.environ.get("SATCHEL_LAPTOP_DEMO_MINE", "").lower()
        in ("1", "true", "yes"),
    )
