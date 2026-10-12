"""HTTP surface of the air-gapped vault: payloads in, payloads out."""

import os
import sys

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from satchel_core.payloads import from_http, to_http

from .approvals import ApprovalRejected, EnvelopeUnavailable
from .seed import WrongPassphrase
from .vault import Vault, VaultLocked


class ExportRequest(BaseModel):
    count: int


class VerifyRequest(BaseModel):
    psbt: dict
    signed: dict


class EnvelopeReleaseRequest(BaseModel):
    approval: dict


class SpendReleaseRequest(BaseModel):
    approval: dict
    psbt: dict


def create_app(vault: Vault) -> FastAPI:
    app = FastAPI(title="satchel-vault")

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError):
        return JSONResponse({"detail": "malformed request"}, status_code=422)

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

    @app.post("/verify")
    def verify(request: VerifyRequest):
        try:
            psbt_payload = from_http(request.psbt)
            signed_payload = from_http(request.signed)
            result = vault.verify(psbt_payload, signed_payload)
        except VaultLocked as exc:
            raise HTTPException(503, str(exc))
        except ValueError as exc:
            raise HTTPException(422, str(exc))
        return to_http(result)

    @app.post("/release/envelope")
    def release_envelope(request: EnvelopeReleaseRequest):
        try:
            approval = from_http(request.approval)
            released = vault.release_envelope(approval)
        except VaultLocked as exc:
            raise HTTPException(503, str(exc))
        except EnvelopeUnavailable as exc:
            raise HTTPException(409, str(exc))
        except ApprovalRejected as exc:
            raise HTTPException(403, str(exc))
        except ValueError as exc:
            raise HTTPException(422, str(exc))
        return to_http(released)

    @app.post("/release/spend")
    def release_spend(request: SpendReleaseRequest):
        try:
            approval = from_http(request.approval)
            psbt_payload = from_http(request.psbt)
            released = vault.release_spend(approval, psbt_payload)
        except VaultLocked as exc:
            raise HTTPException(503, str(exc))
        except ApprovalRejected as exc:
            raise HTTPException(403, str(exc))
        except ValueError as exc:
            raise HTTPException(422, str(exc))
        return to_http(released)

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
