"""HTTP surface of the air-gapped vault: payloads in, payloads out."""

import os
import sys

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from satchel_core.payloads import to_http

from .seed import WrongPassphrase
from .vault import Vault, VaultLocked


class ExportRequest(BaseModel):
    count: int


def create_app(vault: Vault) -> FastAPI:
    app = FastAPI(title="satchel-vault")

    @app.post("/addresses/export")
    def export_addresses(request: ExportRequest):
        try:
            payload = vault.export_receive_addresses(request.count)
        except VaultLocked as exc:
            raise HTTPException(503, str(exc))
        except ValueError as exc:
            raise HTTPException(422, str(exc))
        return to_http(payload)

    @app.get("/envelopes/export")
    def export_envelopes():
        try:
            payload = vault.envelope_export()
        except VaultLocked as exc:
            raise HTTPException(503, str(exc))
        except ValueError as exc:
            raise HTTPException(422, str(exc))
        return to_http(payload)

    return app


def create_app_from_env() -> FastAPI:
    vault = Vault.from_env()
    if vault.initialized and os.environ.get("SATCHEL_VAULT_PASSPHRASE"):
        try:
            vault.unlock(os.environ["SATCHEL_VAULT_PASSPHRASE"])
        except WrongPassphrase:
            print(
                "warning: SATCHEL_VAULT_PASSPHRASE did not unlock the vault",
                file=sys.stderr,
            )
    return create_app(vault)
