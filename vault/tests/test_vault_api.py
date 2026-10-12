"""HTTP API tests, including a route-set/leak check."""

import pytest
from embit import bip32
from embit.networks import NETWORKS
from fastapi.testclient import TestClient

from satchel_core.keys import MasterKey
from satchel_core.payloads import MessageType, from_http
from satchel_vault.app import create_app
from satchel_vault.seed import read_seed_file

from .test_vault import DICE, PASSPHRASE, make_vault

EXPECTED_ROUTES = {
    "/addresses/export",
    "/envelopes/export",
    "/openapi.json",
    "/docs",
    "/docs/oauth2-redirect",
    "/redoc",
}


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
    vault = make_vault(tmp_path)
    app = create_app(vault)
    paths = {route.path for route in app.routes}
    assert paths == EXPECTED_ROUTES
    seed = read_seed_file(tmp_path / "vault" / "seed.json", PASSPHRASE)
    master = MasterKey.from_seed(seed)
    tprv = bip32.HDKey.from_seed(
        seed, version=NETWORKS["regtest"]["xprv"]
    ).to_base58()
    forbidden = [
        seed.hex(),
        tprv,
        master.receive(0).wif,
        master.envelope(0).wif,
        PASSPHRASE,
    ]
    client = TestClient(app)
    calls = {
        "/addresses/export": lambda: client.post("/addresses/export", json={"count": 2}),
        "/envelopes/export": lambda: client.get("/envelopes/export"),
    }
    for path in paths:
        response = calls.get(path, lambda: client.get(path))()
        assert response.status_code == 200
        for secret in forbidden:
            assert secret not in response.text, f"{path} leaked a secret"
