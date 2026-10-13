"""Ledger-gated key release for large spends, and every refusal path.

Satchel grants (fund from main funds, then hand over the key) are covered in
test_satchels.py.
"""

import base64
import hashlib
import json
import secrets
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from satchel_agent.wallet import EnvelopeWallet
from satchel_core.keys import MasterKey
from satchel_core.payloads import MessageType, Payload, to_http
from satchel_core.transactions import Output, SpendInput, build_psbt
from satchel_vault.app import create_app
from satchel_vault.approvals import (
    ApprovalRejected,
    EnvelopeUnavailable,
    render_text,
)
from satchel_vault.seed import WrongPassphrase, unlock_seed_file
from satchel_vault.vault import Vault, VaultLocked

from .test_approvals import (
    LEDGER_SECRET,
    approve_payload,
    ledger_address,
    sign_approval,
    spend_plan,
)

DICE = "1" * 50
PASSPHRASE = "correct horse battery staple"
LEDGER = ledger_address()
BUDGET = 200_000
NONCE = "a" * 16


def make_vault(tmp_path: Path, unlock: bool = True) -> Vault:
    vault = Vault(tmp_path / "vault")
    vault.setup(DICE, PASSPHRASE, LEDGER)
    if unlock:
        vault.unlock(PASSPHRASE)
    return vault


def master_of(tmp_path: Path) -> MasterKey:
    seed, _ = unlock_seed_file(tmp_path / "vault" / "seed.json", PASSPHRASE)
    return MasterKey.from_seed(seed)


def event_types(tmp_path=None) -> list[str]:
    import os

    path = Path(os.environ["SATCHEL_EVENT_LOG"])
    return [json.loads(line)["type"] for line in path.read_text().splitlines()]


def make_spend(
    vault: Vault,
    master: MasterKey,
    destination: str | None = None,
    amount: int = 80_000,
    input_count: int = 2,
):
    """Build a vault-funded spend PSBT plus the matching plan."""
    inputs = []
    for i in range(input_count):
        key = master.receive(i)
        inputs.append(
            SpendInput(
                txid=secrets.token_hex(32),
                vout=0,
                amount_sats=50_000,
                public_key=key.public_key,
                path=key.path,
            )
        )
    dest = destination or MasterKey.from_seed(
        secrets.token_bytes(32)
    ).receive(0).address
    change = master.change(0)
    total_in = input_count * 50_000
    change_amount = total_in - amount - 1_000
    psbt = build_psbt(
        inputs,
        [Output(dest, amount)],
        Output(
            change.address,
            change_amount,
            path=change.path,
            public_key=change.public_key,
        ),
        fingerprint=vault.fingerprint,
    )
    raw = psbt.serialize()
    plan = spend_plan(
        amount_sats=amount,
        destination=dest,
        psbt_sha256=hashlib.sha256(raw).hexdigest(),
    )
    return psbt, raw, plan


def unsigned_psbt_payload(raw: bytes) -> Payload:
    return Payload(
        MessageType.UNSIGNED_PSBT, {"psbt": base64.b64encode(raw).decode()}
    )


def test_valid_spend_release(tmp_path):
    vault = make_vault(tmp_path)
    master = master_of(tmp_path)
    psbt, raw, plan = make_spend(vault, master)
    approval = approve_payload(plan, NONCE)
    released = vault.release_spend(approval, unsigned_psbt_payload(raw))
    body = released.body
    assert body["kind"] == "signing"
    paths = [master.receive(i).path for i in range(2)]
    assert [k["path"] for k in body["keys"]] == paths
    assert [k["wif"] for k in body["keys"]] == [
        master.receive(i).wif for i in range(2)
    ]
    from satchel_signer.signer import sign as signer_sign

    signed = signer_sign(unsigned_psbt_payload(raw), released)
    assert signed.type == MessageType.SIGNED_TX
    assert isinstance(signed.body["tx"], str)
    assert released.body["keys"] == []
    inventory = json.loads(
        (tmp_path / "vault" / "inventory.json").read_text()
    )
    assert inventory["used_nonces"] == [NONCE]
    assert "spend_keys_released" in event_types()


def test_spend_releases_distinct_keys_once(tmp_path):
    vault = make_vault(tmp_path)
    master = master_of(tmp_path)
    key = master.receive(0)
    inputs = [
        SpendInput(
            txid=secrets.token_hex(32),
            vout=v,
            amount_sats=50_000,
            public_key=key.public_key,
            path=key.path,
        )
        for v in (0, 1)
    ]
    change = master.change(0)
    dest = MasterKey.from_seed(secrets.token_bytes(32)).receive(0).address
    psbt = build_psbt(
        inputs,
        [Output(dest, 80_000)],
        Output(change.address, 19_000, path=change.path, public_key=change.public_key),
        fingerprint=vault.fingerprint,
    )
    raw = psbt.serialize()
    plan = spend_plan(
        amount_sats=80_000,
        destination=dest,
        psbt_sha256=hashlib.sha256(raw).hexdigest(),
    )
    released = vault.release_spend(
        approve_payload(plan, NONCE), unsigned_psbt_payload(raw)
    )
    assert len(released.body["keys"]) == 1
    assert released.body["keys"][0]["path"] == key.path


def test_swapped_psbt_rejected(tmp_path):
    vault = make_vault(tmp_path)
    master = master_of(tmp_path)
    psbt, raw, plan = make_spend(vault, master)
    approval = approve_payload(plan, NONCE)
    _, other_raw, _ = make_spend(vault, master)
    assert hashlib.sha256(other_raw).hexdigest() != plan["psbt_sha256"]
    with pytest.raises(ApprovalRejected, match="hash"):
        vault.release_spend(approval, unsigned_psbt_payload(other_raw))


def test_spend_wrong_amount_rejected(tmp_path):
    vault = make_vault(tmp_path)
    master = master_of(tmp_path)
    dest = MasterKey.from_seed(secrets.token_bytes(32)).receive(0).address
    psbt, raw, plan = make_spend(vault, master, destination=dest, amount=80_000)
    plan["amount_sats"] = 70_000
    approval = approve_payload(plan, NONCE)
    with pytest.raises(ApprovalRejected):
        vault.release_spend(approval, unsigned_psbt_payload(raw))


def test_spend_wrong_destination_rejected(tmp_path):
    vault = make_vault(tmp_path)
    master = master_of(tmp_path)
    dest = MasterKey.from_seed(secrets.token_bytes(32)).receive(0).address
    psbt, raw, plan = make_spend(vault, master, destination=dest)
    plan["destination"] = MasterKey.from_seed(
        secrets.token_bytes(32)
    ).receive(0).address
    approval = approve_payload(plan, NONCE)
    with pytest.raises(ApprovalRejected):
        vault.release_spend(approval, unsigned_psbt_payload(raw))


def test_extra_foreign_output_rejected(tmp_path):
    vault = make_vault(tmp_path)
    master = master_of(tmp_path)
    key = master.receive(0)
    inputs = [
        SpendInput(
            txid=secrets.token_hex(32),
            vout=0,
            amount_sats=100_000,
            public_key=key.public_key,
            path=key.path,
        )
    ]
    dest = MasterKey.from_seed(secrets.token_bytes(32)).receive(0).address
    foreign = MasterKey.from_seed(secrets.token_bytes(32)).receive(0).address
    change = master.change(0)
    psbt = build_psbt(
        inputs,
        [Output(dest, 50_000), Output(foreign, 30_000)],
        Output(change.address, 19_000, path=change.path, public_key=change.public_key),
        fingerprint=vault.fingerprint,
    )
    raw = psbt.serialize()
    plan = spend_plan(
        amount_sats=50_000,
        destination=dest,
        psbt_sha256=hashlib.sha256(raw).hexdigest(),
    )
    with pytest.raises(ApprovalRejected, match="foreign"):
        vault.release_spend(
            approve_payload(plan, NONCE), unsigned_psbt_payload(raw)
        )


def test_non_vault_change_rejected(tmp_path):
    vault = make_vault(tmp_path)
    master = master_of(tmp_path)
    key = master.receive(0)
    inputs = [
        SpendInput(
            txid=secrets.token_hex(32),
            vout=0,
            amount_sats=100_000,
            public_key=key.public_key,
            path=key.path,
        )
    ]
    dest = MasterKey.from_seed(secrets.token_bytes(32)).receive(0).address
    foreign_change = MasterKey.from_seed(
        secrets.token_bytes(32)
    ).receive(0).address
    psbt = build_psbt(
        inputs,
        [Output(dest, 80_000)],
        Output(foreign_change, 19_000),
        fingerprint=vault.fingerprint,
    )
    raw = psbt.serialize()
    plan = spend_plan(
        amount_sats=80_000,
        destination=dest,
        psbt_sha256=hashlib.sha256(raw).hexdigest(),
    )
    with pytest.raises(ApprovalRejected):
        vault.release_spend(
            approve_payload(plan, NONCE), unsigned_psbt_payload(raw)
        )


def test_envelope_branch_input_rejected(tmp_path):
    vault = make_vault(tmp_path)
    master = master_of(tmp_path)
    envelope = master.envelope(0)
    inputs = [
        SpendInput(
            txid=secrets.token_hex(32),
            vout=0,
            amount_sats=100_000,
            public_key=envelope.public_key,
            path=envelope.path,
        )
    ]
    dest = MasterKey.from_seed(secrets.token_bytes(32)).receive(0).address
    change = master.change(0)
    psbt = build_psbt(
        inputs,
        [Output(dest, 80_000)],
        Output(change.address, 19_000, path=change.path, public_key=change.public_key),
        fingerprint=vault.fingerprint,
    )
    raw = psbt.serialize()
    plan = spend_plan(
        amount_sats=80_000,
        destination=dest,
        psbt_sha256=hashlib.sha256(raw).hexdigest(),
    )
    with pytest.raises(ApprovalRejected):
        vault.release_spend(
            approve_payload(plan, NONCE), unsigned_psbt_payload(raw)
        )


def test_fee_over_cap_rejected(tmp_path):
    vault = make_vault(tmp_path)
    master = master_of(tmp_path)
    key = master.receive(0)
    inputs = [
        SpendInput(
            txid=secrets.token_hex(32),
            vout=0,
            amount_sats=200_000,
            public_key=key.public_key,
            path=key.path,
        )
    ]
    dest = MasterKey.from_seed(secrets.token_bytes(32)).receive(0).address
    change = master.change(0)
    psbt = build_psbt(
        inputs,
        [Output(dest, 80_000)],
        Output(
            change.address,
            200_000 - 80_000 - 100_001,
            path=change.path,
            public_key=change.public_key,
        ),
        fingerprint=vault.fingerprint,
    )
    raw = psbt.serialize()
    plan = spend_plan(
        amount_sats=80_000,
        destination=dest,
        psbt_sha256=hashlib.sha256(raw).hexdigest(),
    )
    with pytest.raises(ApprovalRejected, match="fee"):
        vault.release_spend(
            approve_payload(plan, NONCE), unsigned_psbt_payload(raw)
        )


def test_spend_rejection_does_not_burn_nonce(tmp_path):
    vault = make_vault(tmp_path)
    master = master_of(tmp_path)
    psbt, raw, plan = make_spend(vault, master)
    _, other_raw, _ = make_spend(vault, master)
    with pytest.raises(ApprovalRejected):
        vault.release_spend(
            approve_payload(plan, NONCE), unsigned_psbt_payload(other_raw)
        )
    from satchel_vault.inventory import Inventory

    assert Inventory(tmp_path / "vault" / "inventory.json").used_nonces == []


def test_http_malformed_and_locked(tmp_path):
    vault = make_vault(tmp_path)
    client = TestClient(create_app(vault))
    bad = client.post("/release/spend", json={"nope": {}})
    assert bad.status_code == 422
    bad2 = client.post(
        "/release/spend", json={"approval": {"bogus": 1}, "psbt": {}}
    )
    assert bad2.status_code == 422
    master = master_of(tmp_path)
    _, raw, plan = make_spend(vault, master)
    locked = Vault(tmp_path / "locked-vault")
    locked_client = TestClient(create_app(locked))
    response = locked_client.post(
        "/release/spend",
        json={
            "approval": to_http(approve_payload(plan, NONCE)),
            "psbt": to_http(unsigned_psbt_payload(raw)),
        },
    )
    assert response.status_code == 503


def test_locked_vault_raises(tmp_path):
    vault = make_vault(tmp_path)
    master = master_of(tmp_path)
    _, raw, plan = make_spend(vault, master)
    locked = Vault(tmp_path / "vault")
    with pytest.raises(VaultLocked):
        locked.release_spend(
            approve_payload(plan, NONCE), unsigned_psbt_payload(raw)
        )


def test_tampered_ledger_address_breaks_unlock(tmp_path):
    make_vault(tmp_path)
    path = tmp_path / "vault" / "seed.json"
    doc = json.loads(path.read_text())
    doc["ledger_address"] = "0x" + "0" * 40
    path.write_text(json.dumps(doc))
    vault = Vault(tmp_path / "vault")
    with pytest.raises(WrongPassphrase):
        vault.unlock(PASSPHRASE)


def test_v1_seed_file_refused(tmp_path):
    import secrets as pysecrets

    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

    salt = pysecrets.token_bytes(16)
    key = Scrypt(salt=salt, length=32, n=2**15, r=8, p=1).derive(
        PASSPHRASE.encode()
    )
    nonce = pysecrets.token_bytes(12)
    doc = {
        "version": 1,
        "kdf": {"name": "scrypt", "n": 2**15, "r": 8, "p": 1, "salt": salt.hex()},
        "cipher": "aes-256-gcm",
        "nonce": nonce.hex(),
        "ciphertext": AESGCM(key)
        .encrypt(nonce, bytes(range(32)), b"satchel-vault-seed-v1")
        .hex(),
        "fingerprint": "deadbeef",
    }
    path = tmp_path / "vault"
    path.mkdir()
    (path / "seed.json").write_text(json.dumps(doc))
    vault = Vault(path)
    with pytest.raises(ValueError, match="predates Ledger registration"):
        vault.unlock(PASSPHRASE)


def test_concurrent_spend_release_only_one_wins(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    vault = make_vault(tmp_path)
    master = master_of(tmp_path)
    _, raw, plan = make_spend(vault, master)
    approval = approve_payload(plan, NONCE)
    psbt_payload = unsigned_psbt_payload(raw)

    def attempt():
        try:
            vault.release_spend(approval, psbt_payload)
            return "ok"
        except ApprovalRejected:
            return "rejected"

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = [f.result() for f in [
            pool.submit(attempt) for _ in range(8)
        ]]
    assert results.count("ok") == 1
    assert results.count("rejected") == 7
    inventory = json.loads(
        (tmp_path / "vault" / "inventory.json").read_text()
    )
    assert inventory["used_nonces"].count(NONCE) == 1
