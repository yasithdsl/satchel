"""Plan validation, canonical text, and EIP-191 recovery."""

import json
from pathlib import Path

import pytest
from Crypto.Hash import keccak
from embit.util import secp256k1

from satchel_core.payloads import MessageType, Payload
from satchel_vault.approvals import (
    ApprovalRejected,
    eip191_recover,
    render_text,
    validate_plan,
)

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"
LEDGER_SECRET = (1).to_bytes(32, "big")


def ledger_address(secret: bytes = LEDGER_SECRET) -> str:
    pub = secp256k1.ec_pubkey_create(secret)
    raw = secp256k1.ec_pubkey_serialize(pub, secp256k1.EC_UNCOMPRESSED)
    digest = keccak.new(digest_bits=256, data=raw[1:]).digest()
    return "0x" + digest[-20:].hex()


def sign_approval(text: str, secret: bytes = LEDGER_SECRET) -> str:
    msg = text.encode()
    digest = keccak.new(
        digest_bits=256,
        data=b"\x19Ethereum Signed Message:\n" + str(len(msg)).encode() + msg,
    ).digest()
    recsig = secp256k1.ecdsa_sign_recoverable(digest, secret)
    compact, recid = secp256k1.ecdsa_recoverable_signature_serialize_compact(
        recsig
    )
    return "0x" + (compact + bytes([27 + recid])).hex()


def approve_payload(
    plan: dict,
    nonce: str,
    *,
    text: str | None = None,
    secret: bytes = LEDGER_SECRET,
    address: str | None = None,
) -> Payload:
    text = render_text(plan, nonce) if text is None else text
    return Payload(
        MessageType.LEDGER_APPROVAL,
        {
            "plan": plan,
            "text": text,
            "nonce": nonce,
            "signature": sign_approval(text, secret),
            "address": ledger_address(secret) if address is None else address,
            "path": "44'/60'/0'/0/0",
        },
    )


def satchel_plan(**overrides) -> dict:
    plan = {
        "kind": "satchel_grant",
        "satchel_index": 0,
        "agent_id": "shopping-agent",
        "budget_sats": 200_000,
        "expires_at": 2_000_000_040,
        "psbt_sha256": "cd" * 32,
    }
    plan.update(overrides)
    return plan


def spend_plan(**overrides) -> dict:
    plan = {
        "kind": "large_spend",
        "amount_sats": 1_000_000,
        "destination": "bcrt1qw508d6qejxtdg4y5r3zarvary0c5xw7kygt080",
        "purpose": "laptop",
        "psbt_sha256": "ab" * 32,
    }
    plan.update(overrides)
    return plan


def test_test_ledger_address_matches_ethers_vector():
    assert ledger_address() == "0x7e5f4552091a69125d5dfcb7b8c2659029395bdf"


def test_text_vectors_render_identically():
    vectors = json.loads((FIXTURES / "approval_text_vectors.json").read_text())
    for vector in vectors:
        plan = vector["plan"]
        validate_plan(plan)
        assert render_text(plan, vector["nonce"]) == vector["text"]


def test_eip191_vectors_recover():
    vectors = json.loads((FIXTURES / "eip191_vectors.json").read_text())
    for vector in vectors:
        assert eip191_recover(vector["message"], vector["signature"]) == (
            vector["address"].lower()
        ), vector["source"]


@pytest.mark.parametrize(
    "plan",
    [
        {**satchel_plan(), "extra": 1},
        {k: v for k, v in satchel_plan().items() if k != "agent_id"},
        {k: v for k, v in satchel_plan().items() if k != "psbt_sha256"},
        {**satchel_plan(), "kind": "envelope_grant"},
        satchel_plan(satchel_index=-1),
        satchel_plan(satchel_index=2**31),
        satchel_plan(satchel_index=True),
        satchel_plan(budget_sats=0),
        satchel_plan(budget_sats=2_100_000_000_000_001),
        satchel_plan(budget_sats=1.5),
        satchel_plan(expires_at=61),
        satchel_plan(expires_at=0),
        satchel_plan(expires_at=253_402_300_800),
        satchel_plan(agent_id="bad\nnewline"),
        satchel_plan(agent_id="emoji 😀"),
        satchel_plan(agent_id=""),
        satchel_plan(agent_id="x" * 33),
        satchel_plan(agent_id=" leading"),
        satchel_plan(psbt_sha256="CD" * 32),
        spend_plan(destination="bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4"),
        spend_plan(purpose="bad\tpurpose"),
        spend_plan(psbt_sha256="AB" * 32),
        spend_plan(psbt_sha256="ab" * 31),
        spend_plan(amount_sats="1000"),
        {"kind": "unknown"},
        "not a dict",
    ],
)
def test_invalid_plans(plan):
    with pytest.raises(ValueError):
        validate_plan(plan)


def test_signature_format_enforced():
    with pytest.raises(ValueError):
        eip191_recover("hello", "0xABCDEF" + "0" * 124)
    with pytest.raises(ValueError):
        eip191_recover("hello", "0x" + "0" * 128)
    with pytest.raises(ValueError):
        eip191_recover("hello", "00" + "0" * 128)


def test_v_values_accepted():
    text = "test message"
    msg = text.encode()
    digest = keccak.new(
        digest_bits=256,
        data=b"\x19Ethereum Signed Message:\n" + str(len(msg)).encode() + msg,
    ).digest()
    recsig = secp256k1.ecdsa_sign_recoverable(digest, LEDGER_SECRET)
    compact, recid = secp256k1.ecdsa_recoverable_signature_serialize_compact(
        recsig
    )
    for v in (recid, 27 + recid):
        sig = "0x" + (compact + bytes([v])).hex()
        assert eip191_recover(text, sig) == ledger_address()
    with pytest.raises(ValueError):
        eip191_recover(text, "0x" + (compact + bytes([29])).hex())


def test_wrong_key_does_not_recover_to_ledger():
    text = "test"
    signature = sign_approval(text, (2).to_bytes(32, "big"))
    assert eip191_recover(text, signature) != ledger_address()


def test_satchel_text_states_funding_and_handover():
    text = render_text(satchel_plan(), "0123456789abcdef")
    assert text == (
        "Create a 0.002 BTC satchel #0 for shopping-agent from main funds, "
        "expires 18 May 03:34 UTC. Nonce 0123456789abcdef"
    )
