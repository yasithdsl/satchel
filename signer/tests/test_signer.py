"""Signer tests: offline signing, refusal paths, regtest end-to-end."""

import base64
import json
import os
import secrets
from pathlib import Path

import pytest
from embit.transaction import Transaction
from fastapi.testclient import TestClient

from satchel_core.keys import MasterKey
from satchel_core.payloads import (
    MessageType,
    Payload,
    from_http,
    to_http,
)
from satchel_core.transactions import Output, SpendInput, build_psbt
from satchel_signer.app import SignRequest, create_app
from satchel_signer.signer import sign


def make_release(*keys):
    return Payload(
        MessageType.KEY_RELEASE,
        {
            "kind": "signing",
            "keys": [{"path": k.path, "wif": k.wif} for k in keys],
        },
    )


def make_psbt(master, n=2):
    keys = [master.envelope(i) for i in range(n)]
    dest = MasterKey.from_seed(secrets.token_bytes(32)).receive(0).address
    inputs = [
        SpendInput(secrets.token_hex(32), i, 50_000, key.public_key)
        for i, key in enumerate(keys)
    ]
    psbt = build_psbt(
        inputs, [Output(dest, 80_000)], Output(keys[0].address, 19_000)
    )
    return keys, Payload(
        MessageType.UNSIGNED_PSBT, {"psbt": psbt.to_base64()}
    )


def event_log() -> str:
    return Path(os.environ["SATCHEL_EVENT_LOG"]).read_text()


def test_signs_two_input_psbt():
    master = MasterKey.from_seed(secrets.token_bytes(32))
    keys, payload = make_psbt(master)
    signed = sign(payload, make_release(*keys))
    assert signed.type == MessageType.SIGNED_TX
    tx = Transaction.parse(bytes.fromhex(signed.body["tx"]))
    assert tx.txid().hex() == signed.body["txid"]
    assert len(tx.vin) == 2
    assert "psbt_signed" in event_log()


def test_signing_is_deterministic():
    master = MasterKey.from_seed(secrets.token_bytes(32))
    keys, payload = make_psbt(master)
    first = sign(payload, make_release(*keys))
    second = sign(payload, make_release(*keys))
    assert first.body["tx"] == second.body["tx"]


def test_release_is_consumed():
    master = MasterKey.from_seed(secrets.token_bytes(32))
    keys, payload = make_psbt(master)
    release = make_release(*keys)
    sign(payload, release)
    assert release.body["keys"] == []


@pytest.mark.parametrize(
    "case",
    [
        "bad_psbt_type",
        "undecodable_psbt",
        "wrong_release_type",
        "wrong_kind",
        "missing_key",
        "extra_key",
        "duplicate_key",
    ],
)
def test_release_consumed_on_every_refusal(case):
    master = MasterKey.from_seed(secrets.token_bytes(32))
    keys, payload = make_psbt(master)
    if case == "bad_psbt_type":
        psbt_payload = Payload(MessageType.SIGNED_TX, {})
        release = make_release(*keys)
    elif case == "undecodable_psbt":
        psbt_payload = Payload(MessageType.UNSIGNED_PSBT, {"psbt": "!!!"})
        release = make_release(*keys)
    elif case == "wrong_release_type":
        psbt_payload = payload
        release = Payload(MessageType.UNSIGNED_PSBT, payload.body)
    elif case == "wrong_kind":
        psbt_payload = payload
        release = Payload(
            MessageType.KEY_RELEASE,
            {"kind": "agent", "keys": make_release(*keys).body["keys"]},
        )
    elif case == "missing_key":
        psbt_payload = payload
        release = make_release(keys[0])
    elif case == "extra_key":
        psbt_payload = payload
        release = make_release(*keys, master.envelope(9))
    else:
        psbt_payload = payload
        release = make_release(*keys, keys[0])
    with pytest.raises(ValueError):
        sign(psbt_payload, release)
    assert release.body.get("keys", []) == []


def test_endpoint_empties_request_keys():
    master = MasterKey.from_seed(secrets.token_bytes(32))
    keys, payload = make_psbt(master)
    app = create_app()
    endpoint = next(
        route.endpoint for route in app.routes if route.path == "/sign"
    )
    request = SignRequest(
        psbt=to_http(payload), keys=to_http(make_release(*keys))
    )
    result = endpoint(request)
    assert request.keys == {}
    assert result["type"] == MessageType.SIGNED_TX


def test_missing_key_refused():
    master = MasterKey.from_seed(secrets.token_bytes(32))
    keys, payload = make_psbt(master)
    with pytest.raises(ValueError):
        sign(payload, make_release(keys[0]))


def test_extra_key_refused():
    master = MasterKey.from_seed(secrets.token_bytes(32))
    keys, payload = make_psbt(master)
    with pytest.raises(ValueError):
        sign(payload, make_release(*keys, master.envelope(9)))


def test_duplicate_key_refused():
    master = MasterKey.from_seed(secrets.token_bytes(32))
    keys, payload = make_psbt(master)
    with pytest.raises(ValueError):
        sign(payload, make_release(*keys, keys[0]))


def test_wrong_payload_types_refused():
    master = MasterKey.from_seed(secrets.token_bytes(32))
    keys, payload = make_psbt(master)
    with pytest.raises(ValueError):
        sign(Payload(MessageType.SIGNED_TX, payload.body), make_release(*keys))
    with pytest.raises(ValueError):
        sign(payload, Payload(MessageType.UNSIGNED_PSBT, payload.body))
    wrong_kind = Payload(
        MessageType.KEY_RELEASE,
        {"kind": "agent", "keys": make_release(*keys).body["keys"]},
    )
    with pytest.raises(ValueError):
        sign(payload, wrong_kind)


def test_malformed_psbt_refused():
    master = MasterKey.from_seed(secrets.token_bytes(32))
    keys, _ = make_psbt(master)
    release = make_release(*keys)
    for bad in ("!!!", base64.b64encode(b"junk").decode(), 42, None):
        with pytest.raises(ValueError):
            sign(Payload(MessageType.UNSIGNED_PSBT, {"psbt": bad}), release)


def test_malformed_wif_refused():
    master = MasterKey.from_seed(secrets.token_bytes(32))
    keys, payload = make_psbt(master)
    release = Payload(
        MessageType.KEY_RELEASE,
        {
            "kind": "signing",
            "keys": [
                {"path": k.path, "wif": wif}
                for k, wif in zip(keys, ["not-a-wif", keys[1].wif])
            ],
        },
    )
    with pytest.raises(ValueError):
        sign(payload, release)


def test_refusal_events_have_no_keys():
    master = MasterKey.from_seed(secrets.token_bytes(32))
    keys, payload = make_psbt(master)
    with pytest.raises(ValueError):
        sign(payload, make_release(keys[0]))
    sign(payload, make_release(*keys))
    log = event_log()
    assert "sign_refused" in log
    for key in keys:
        assert key.wif not in log


def test_sign_writes_no_files(tmp_path, monkeypatch):
    log_dir = tmp_path / "log"
    log_dir.mkdir()
    monkeypatch.setenv("SATCHEL_EVENT_LOG", str(log_dir / "events.jsonl"))
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)
    master = MasterKey.from_seed(secrets.token_bytes(32))
    keys, payload = make_psbt(master)
    sign(payload, make_release(*keys))
    assert list(work.iterdir()) == []


def test_app_sign_round_trip():
    master = MasterKey.from_seed(secrets.token_bytes(32))
    keys, payload = make_psbt(master)
    client = TestClient(create_app())
    response = client.post(
        "/sign",
        json={
            "psbt": to_http(payload),
            "keys": to_http(make_release(*keys)),
        },
    )
    assert response.status_code == 200
    body = from_http(response.json())
    assert body.type == MessageType.SIGNED_TX
    Transaction.parse(bytes.fromhex(body.body["tx"]))


def test_app_refusals_are_422():
    master = MasterKey.from_seed(secrets.token_bytes(32))
    keys, payload = make_psbt(master)
    client = TestClient(create_app())

    def post(release):
        return client.post(
            "/sign", json={"psbt": to_http(payload), "keys": to_http(release)}
        )

    assert post(make_release(keys[0])).status_code == 422
    assert post(make_release(*keys, master.envelope(9))).status_code == 422
    assert post(make_release(*keys, keys[0])).status_code == 422
    assert (
        post(Payload(MessageType.UNSIGNED_PSBT, payload.body)).status_code
        == 422
    )
    bad_type = client.post(
        "/sign",
        json={
            "psbt": to_http(Payload(MessageType.SIGNED_TX, payload.body)),
            "keys": to_http(make_release(*keys)),
        },
    )
    assert bad_type.status_code == 422


def test_app_malformed_bodies_never_echo_wifs():
    master = MasterKey.from_seed(secrets.token_bytes(32))
    keys, payload = make_psbt(master)
    wifs = [k.wif for k in keys]
    client = TestClient(create_app())
    release = make_release(*keys)
    bodies = [
        {"psbt": to_http(payload), "keys": wifs[0]},
        {"psbt": to_http(payload), "keys": {"oops": wifs}},
        {"psbt": wifs[0], "keys": to_http(release)},
        {"psbt": {"parts": wifs}, "keys": to_http(release)},
        {"keys": to_http(release)},
        {},
        "just a string",
    ]
    bodies.append(
        {
            "psbt": to_http(payload),
            "keys": {
                "type": "key_release",
                "parts": ["B$ZJ0100junk"],
                "wif": wifs[0],
            },
        }
    )
    for body in bodies:
        response = client.post("/sign", json=body)
        assert response.status_code == 422, body
        for wif in wifs:
            assert wif not in response.text


@pytest.mark.regtest
def test_regtest_sign_accepted(node):
    master = MasterKey.from_seed(secrets.token_bytes(32))
    k_recv, k_env = master.receive(0), master.envelope(0)
    node.fund_address(k_recv.address, 60_000)
    node.fund_address(k_env.address, 40_000)
    by_address = {k_recv.address: k_recv, k_env.address: k_env}
    utxos = node.list_unspent([k_recv.address, k_env.address])
    inputs = [
        SpendInput(
            u.txid, u.vout, u.amount_sats, by_address[u.address].public_key
        )
        for u in utxos
    ]
    dest = MasterKey.from_seed(secrets.token_bytes(32)).receive(0).address
    psbt = build_psbt(
        inputs, [Output(dest, 80_000)], Output(k_recv.address, 19_000)
    )
    payload = Payload(MessageType.UNSIGNED_PSBT, {"psbt": psbt.to_base64()})
    client = TestClient(create_app())
    response = client.post(
        "/sign",
        json={
            "psbt": to_http(payload),
            "keys": to_http(make_release(k_recv, k_env)),
        },
    )
    assert response.status_code == 200
    signed = from_http(response.json())
    accepted = node.call("testmempoolaccept", [signed.body["tx"]])[0]
    assert accepted["allowed"], accepted
