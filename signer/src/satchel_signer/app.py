"""HTTP surface of the air-gapped signer: payloads in, payloads out."""

import os

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from satchel_core.events import emit
from satchel_core.payloads import from_http, to_http

from .signer import sign

RANDOM_NONCE_ENV = "SATCHEL_SIGNER_RANDOM_NONCE"
_TRUTHY = {"1", "true", "yes"}


class SignRequest(BaseModel):
    psbt: dict
    keys: dict


class DemoRequest(BaseModel):
    enabled: bool


def create_app(random_nonce: bool = False) -> FastAPI:
    app = FastAPI(title="satchel-signer")
    app.state.random_nonce = random_nonce
    if random_nonce:
        emit(
            "signer",
            "random_nonce_enabled",
            "DEMO random-nonce signing enabled",
            {"enabled": True},
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError):
        return JSONResponse(
            {"detail": "malformed request"}, status_code=422
        )

    @app.get("/health")
    def health():
        return {"ok": True, "random_nonce": app.state.random_nonce}

    @app.post("/sign")
    def sign_endpoint(request: SignRequest):
        try:
            psbt_payload = from_http(request.psbt)
            release = from_http(request.keys)
            signed = sign(
                psbt_payload,
                release,
                random_nonce=app.state.random_nonce,
            )
        except ValueError as exc:
            raise HTTPException(422, str(exc))
        finally:
            request.keys.clear()
        return to_http(signed)

    @app.get("/demo/random-nonce")
    def demo_state():
        return {"enabled": app.state.random_nonce}

    @app.post("/demo/random-nonce")
    def demo_set(request: DemoRequest):
        app.state.random_nonce = request.enabled
        emit(
            "signer",
            "random_nonce_enabled" if request.enabled
            else "random_nonce_disabled",
            f"DEMO random-nonce signing "
            f"{'enabled' if request.enabled else 'disabled'}",
            {"enabled": request.enabled},
        )
        return {"enabled": app.state.random_nonce}

    return app


def create_app_from_env() -> FastAPI:
    enabled = os.environ.get(RANDOM_NONCE_ENV, "").strip().lower() in _TRUTHY
    return create_app(random_nonce=enabled)
