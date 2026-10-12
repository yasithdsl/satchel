"""DEMO random-nonce signer tests (offline)."""

import base64
import json
import secrets

import pytest
from embit.psbt import PSBT
from embit.transaction import Transaction
from fastapi.testclient import TestClient

from satchel_core.keys import MasterKey
from satchel_core.payloads import (
    MessageType,
    Payload,
    from_http,
    to_http,
)
from satchel_core.signing import (
    SECP256K1_N,
    is_low_s,
    sign_digest,
    verify_digest,
)
from satchel_core.transactions import input_sighashes
from satchel_signer.app import create_app, create_app_from_env
from satchel_signer.random_nonce import _random_nonce
from satchel_signer.signer import sign

from .test_signer import event_log, make_psbt, make_release


def events() -> list[dict]:
    return [json.loads(line) for line in event_log().splitlines()]


def test_random_nonce_ignores_arguments():
    values = {_random_nonce(5, 7, extra_data=b"x") for _ in range(16)}
    assert len(values) > 1
    assert all(1 <= v < SECP256K1_N for v in values)


def test_random_mode_signatures_valid_not_deterministic():
    master = MasterKey.from_seed(secrets.token_bytes(32))
    keys, payload = make_psbt(master)
    signed = sign(payload, make_release(*keys), random_nonce=True)
    psbt = PSBT.parse(base64.b64decode(payload.body["psbt"]))
    sighashes = input_sighashes(psbt)
    tx = Transaction.parse(bytes.fromhex(signed.body["tx"]))
    assert tx.txid().hex() == signed.body["txid"] == psbt.tx.txid().hex()
    for i, key in enumerate(keys):
        raw_sig = tx.vin[i].witness.items[0]
        assert raw_sig[-1] == 0x01
        der = raw_sig[:-1]
        assert verify_digest(key.public_key, sighashes[i], der)
        assert is_low_s(der)
        assert der != sign_digest(key.wif, sighashes[i])


def test_random_mode_is_not_deterministic():
    master = MasterKey.from_seed(secrets.token_bytes(32))
    keys, payload = make_psbt(master)
    first = sign(payload, make_release(*keys), random_nonce=True)
    second = sign(payload, make_release(*keys), random_nonce=True)
    assert first.body["tx"] != second.body["tx"]
    assert first.body["txid"] == second.body["txid"]


def test_random_mode_events_and_hygiene():
    master = MasterKey.from_seed(secrets.token_bytes(32))
    keys, payload = make_psbt(master)
    release = make_release(*keys)
    sign(payload, release, random_nonce=True)
    assert release.body["keys"] == []
    entries = events()
    assert any(e["type"] == "random_nonce_signing" for e in entries)
    signed_event = next(e for e in entries if e["type"] == "psbt_signed")
    assert signed_event["payload"]["nonce"] == "random"
    log = event_log()
    for key in keys:
        assert key.wif not in log


def test_random_mode_still_refuses_bad_keys():
    master = MasterKey.from_seed(secrets.token_bytes(32))
    keys, payload = make_psbt(master)
    with pytest.raises(ValueError):
        sign(payload, make_release(keys[0]), random_nonce=True)
    with pytest.raises(ValueError):
        sign(
            payload,
            make_release(*keys, master.envelope(9)),
            random_nonce=True,
        )


def test_default_mode_stays_deterministic():
    master = MasterKey.from_seed(secrets.token_bytes(32))
    keys, payload = make_psbt(master)
    first = sign(payload, make_release(*keys))
    second = sign(payload, make_release(*keys))
    assert first.body["tx"] == second.body["tx"]
    signed_event = next(e for e in events() if e["type"] == "psbt_signed")
    assert signed_event["payload"]["nonce"] == "rfc6979"


def test_demo_flag_api_toggle():
    master = MasterKey.from_seed(secrets.token_bytes(32))
    keys, payload = make_psbt(master)
    psbt = PSBT.parse(base64.b64decode(payload.body["psbt"]))
    sighashes = input_sighashes(psbt)
    client = TestClient(create_app())
    assert client.get("/demo/random-nonce").json() == {"enabled": False}

    response = client.post(
        "/demo/random-nonce", json={"enabled": True}
    )
    assert response.json() == {"enabled": True}
    assert "random_nonce_enabled" in event_log()
    response = client.post(
        "/sign",
        json={
            "psbt": to_http(payload),
            "keys": to_http(make_release(*keys)),
        },
    )
    assert response.status_code == 200
    signed = from_http(response.json())
    tx = Transaction.parse(bytes.fromhex(signed.body["tx"]))
    for i, key in enumerate(keys):
        der = tx.vin[i].witness.items[0][:-1]
        assert der != sign_digest(key.wif, sighashes[i])
        assert verify_digest(key.public_key, sighashes[i], der)

    response = client.post(
        "/demo/random-nonce", json={"enabled": False}
    )
    assert response.json() == {"enabled": False}
    assert "random_nonce_disabled" in event_log()
    response = client.post(
        "/sign",
        json={
            "psbt": to_http(payload),
            "keys": to_http(make_release(*keys)),
        },
    )
    tx = Transaction.parse(bytes.fromhex(from_http(response.json()).body["tx"]))
    for i, key in enumerate(keys):
        assert tx.vin[i].witness.items[0][:-1] == sign_digest(
            key.wif, sighashes[i]
        )


def test_demo_flag_bad_body_is_generic_422():
    client = TestClient(create_app())
    for body in ({"enabled": "bogus"}, {}, "yes"):
        response = client.post("/demo/random-nonce", json=body)
        assert response.status_code == 422
        assert response.json() == {"detail": "malformed request"}


def test_env_var_enables_demo(monkeypatch):
    monkeypatch.setenv("SATCHEL_SIGNER_RANDOM_NONCE", "Yes")
    app = create_app_from_env()
    assert TestClient(app).get("/demo/random-nonce").json() == {
        "enabled": True
    }
    assert "random_nonce_enabled" in event_log()


def test_env_var_unset_stays_deterministic(monkeypatch):
    monkeypatch.delenv("SATCHEL_SIGNER_RANDOM_NONCE", raising=False)
    app = create_app_from_env()
    assert TestClient(app).get("/demo/random-nonce").json() == {
        "enabled": False
    }
