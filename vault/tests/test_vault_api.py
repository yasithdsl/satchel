"""HTTP API tests, including a route-set/leak check."""

import secrets

import pytest
from embit import bip32
from embit.networks import NETWORKS
from embit.transaction import Transaction
from fastapi.testclient import TestClient

from satchel_core.keys import MasterKey
from satchel_core.payloads import MessageType, Payload, from_http, to_http
from satchel_core.transactions import (
    Output,
    SpendInput,
    build_psbt,
    finalize_psbt,
    sign_psbt,
)
from satchel_vault.app import create_app
from satchel_vault.seed import read_seed_file

from .test_vault import DICE, PASSPHRASE, make_vault

EXPECTED_ROUTES = {
    "/health",
    "/addresses/export",
    "/envelopes/export",
    "/verify",
    "/satchels/reserve",
    "/release/satchel-funding",
    "/release/satchel",
    "/release/spend",
    "/openapi.json",
    "/docs",
    "/docs/oauth2-redirect",
    "/redoc",
}


def make_verify_bodies(vault, master):
    keys = [master.receive(0), master.receive(1)]
    inputs = [
        SpendInput(secrets.token_hex(32), i, 50_000, k.public_key, path=k.path)
        for i, k in enumerate(keys)
    ]
    psbt = build_psbt(
        inputs,
        [Output(master.envelope(0).address, 80_000)],
        Output(keys[0].address, 19_000),
        fingerprint=vault.fingerprint,
    )
    raw = finalize_psbt(sign_psbt(psbt, [k.wif for k in keys]))
    unsigned = Payload(MessageType.UNSIGNED_PSBT, {"psbt": psbt.to_base64()})
    txid = Transaction.parse(bytes.fromhex(raw)).txid().hex()
    signed = Payload(MessageType.SIGNED_TX, {"tx": raw, "txid": txid})
    return unsigned, signed, raw


def test_health(tmp_path):
    client = TestClient(create_app(make_vault(tmp_path)))
    body = client.get("/health").json()
    assert body == {"ok": True, "initialized": True}


def test_export_round_trip(tmp_path):
    client = TestClient(create_app(make_vault(tmp_path)))
    response = client.post("/addresses/export", json={"count": 3})
    assert response.status_code == 200
    payload = from_http(response.json())
    assert payload.type == MessageType.ADDRESS_EXPORT
    assert [a["index"] for a in payload.body["addresses"]] == [0, 1, 2]


def test_locked_returns_503(tmp_path):
    from satchel_vault.vault import Vault

    client = TestClient(create_app(Vault(tmp_path / "vault")))
    assert client.post("/addresses/export", json={"count": 1}).status_code == 503
    assert client.get("/envelopes/export").status_code == 503


@pytest.mark.parametrize("body", [{"count": 0}, {"count": 101}, {"count": "abc"}])
def test_bad_count_returns_422(tmp_path, body):
    client = TestClient(create_app(make_vault(tmp_path)))
    assert client.post("/addresses/export", json=body).status_code == 422


def test_route_set_and_no_secret_leaks(tmp_path):
    import base64
    import hashlib

    from satchel_vault.vault import Vault

    from .test_approvals import (
        approve_payload,
        ledger_address,
        satchel_plan,
        spend_plan,
    )
    from .test_satchels import FUTURE, funding_psbt, proof_for, sign_and_verify

    vault = Vault(tmp_path / "vault")
    vault.setup(DICE, PASSPHRASE, ledger_address())
    vault.unlock(PASSPHRASE)
    app = create_app(vault)
    paths = {route.path for route in app.routes}
    assert paths == EXPECTED_ROUTES
    seed = read_seed_file(tmp_path / "vault" / "seed.json", PASSPHRASE)
    master = MasterKey.from_seed(seed)
    tprv = bip32.HDKey.from_seed(
        seed, version=NETWORKS["regtest"]["xprv"]
    ).to_base58()
    unsigned, signed, raw = make_verify_bodies(vault, master)
    signatures = [
        vin.witness.items[0].hex()
        for vin in Transaction.parse(bytes.fromhex(raw)).vin
    ]
    spend_keys = [master.receive(0), master.receive(1)]
    spend_inputs = [
        SpendInput(secrets.token_hex(32), i, 50_000, k.public_key, path=k.path)
        for i, k in enumerate(spend_keys)
    ]
    spend_change = master.change(0)
    spend_dest = MasterKey.from_seed(secrets.token_bytes(32)).receive(0).address
    spend_psbt = build_psbt(
        spend_inputs,
        [Output(spend_dest, 80_000)],
        Output(
            spend_change.address,
            19_000,
            path=spend_change.path,
            public_key=spend_change.public_key,
        ),
        fingerprint=vault.fingerprint,
    )
    spend_raw = spend_psbt.serialize()
    spend_unsigned = Payload(
        MessageType.UNSIGNED_PSBT,
        {"psbt": base64.b64encode(spend_raw).decode()},
    )
    # Satchel 0: reserved; the route releases the main-fund keys that fund it.
    satchel0 = vault.reserve_satchel(200_000).body["addresses"][0]
    _, funding0_raw = funding_psbt(vault, master, satchel0["address"], 200_000)
    funding0_unsigned = Payload(
        MessageType.UNSIGNED_PSBT,
        {"psbt": base64.b64encode(funding0_raw).decode()},
    )
    funding0_approval = approve_payload(
        satchel_plan(
            satchel_index=0,
            budget_sats=200_000,
            expires_at=FUTURE,
            psbt_sha256=hashlib.sha256(funding0_raw).hexdigest(),
        ),
        "a" * 16,
    )
    # Satchel 1: funded, verified and confirmed; the route hands over its key.
    satchel1 = vault.reserve_satchel(100_000).body["addresses"][0]
    funding1_psbt, funding1_raw = funding_psbt(
        vault, master, satchel1["address"], 100_000
    )
    funding1_keys = vault.release_satchel_funding(
        approve_payload(
            satchel_plan(
                satchel_index=1,
                budget_sats=100_000,
                expires_at=FUTURE,
                psbt_sha256=hashlib.sha256(funding1_raw).hexdigest(),
            ),
            "c" * 16,
        ),
        Payload(
            MessageType.UNSIGNED_PSBT,
            {"psbt": base64.b64encode(funding1_raw).decode()},
        ),
    )
    funding1_txid = sign_and_verify(vault, funding1_psbt, funding1_keys, funding1_raw)
    spend_approval = approve_payload(
        spend_plan(
            amount_sats=80_000,
            destination=spend_dest,
            psbt_sha256=hashlib.sha256(spend_raw).hexdigest(),
        ),
        "b" * 16,
    )
    forbidden = [
        seed.hex(),
        tprv,
        master.envelope(0).wif,
        master.envelope(2).wif,
        master.receive(2).wif,
        master.change(0).wif,
        PASSPHRASE,
        *signatures,
    ]
    client = TestClient(app)
    calls = {
        "/addresses/export": lambda: client.post("/addresses/export", json={"count": 2}),
        "/envelopes/export": lambda: client.get("/envelopes/export"),
        "/verify": lambda: client.post(
            "/verify",
            json={"psbt": to_http(unsigned), "signed": to_http(signed)},
        ),
        "/satchels/reserve": lambda: client.post(
            "/satchels/reserve", json={"budget_sats": 50_000}
        ),
        "/release/satchel-funding": lambda: client.post(
            "/release/satchel-funding",
            json={
                "approval": to_http(funding0_approval),
                "psbt": to_http(funding0_unsigned),
            },
        ),
        "/release/satchel": lambda: client.post(
            "/release/satchel",
            json={"proof": to_http(proof_for(1, funding1_txid))},
        ),
        "/release/spend": lambda: client.post(
            "/release/spend",
            json={
                "approval": to_http(spend_approval),
                "psbt": to_http(spend_unsigned),
            },
        ),
    }
    released_wifs = {
        "/release/satchel-funding": [master.receive(i).wif for i in range(2)],
        "/release/satchel": [master.envelope(1).wif],
        "/release/spend": [k.wif for k in spend_keys],
    }
    all_wifs = [master.envelope(i).wif for i in range(3)] + [
        master.receive(i).wif for i in range(3)
    ]
    for path in paths:
        response = calls.get(path, lambda: client.get(path))()
        assert response.status_code == 200
        for secret in forbidden:
            assert secret not in response.text, f"{path} leaked a secret"
        allowed = released_wifs.get(path, [])
        for wif in all_wifs:
            if wif not in allowed:
                assert wif not in response.text, f"{path} leaked an unrelated key"


def test_verify_endpoint_round_trip(tmp_path):
    vault = make_vault(tmp_path)
    seed = read_seed_file(tmp_path / "vault" / "seed.json", PASSPHRASE)
    master = MasterKey.from_seed(seed)
    unsigned, signed, _ = make_verify_bodies(vault, master)
    client = TestClient(create_app(vault))
    response = client.post(
        "/verify",
        json={"psbt": to_http(unsigned), "signed": to_http(signed)},
    )
    assert response.status_code == 200
    result = from_http(response.json())
    assert result.type == MessageType.VERIFICATION_RESULT
    assert result.body["result"] == "pass"


def test_verify_bad_payloads_422(tmp_path):
    vault = make_vault(tmp_path)
    seed = read_seed_file(tmp_path / "vault" / "seed.json", PASSPHRASE)
    master = MasterKey.from_seed(seed)
    unsigned, signed, _ = make_verify_bodies(vault, master)
    client = TestClient(create_app(vault))
    assert (
        client.post(
            "/verify",
            json={"psbt": to_http(signed), "signed": to_http(signed)},
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/verify",
            json={"psbt": to_http(unsigned), "signed": to_http(unsigned)},
        ).status_code
        == 422
    )
