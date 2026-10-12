"""HTTP surface of the laptop coordinator."""

from dataclasses import asdict

import httpx
from fastapi import FastAPI, HTTPException

from satchel_core.regtest import NodeUnavailable, RegtestNode

from .envelopes import envelope_statuses
from .state import LaptopState
from .vault_client import VaultClient


def create_app(
    vault_client: VaultClient, node: RegtestNode, state: LaptopState
) -> FastAPI:
    app = FastAPI(title="satchel-laptop")

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

    return app


def create_app_from_env() -> FastAPI:
    return create_app(VaultClient(), RegtestNode.from_env(), LaptopState.from_env())
