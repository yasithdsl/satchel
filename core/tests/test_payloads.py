"""Tests for versioned JSON payloads and their QR transport."""

import json
import random
import secrets

import pytest
from embit.psbt import PSBT

from satchel_core.keys import MasterKey
from satchel_core.payloads import (
    MessageType,
    Payload,
    decode,
    encode,
    from_qr_parts,
    render_payload,
    to_qr_parts,
)
from satchel_core.transactions import Output, SpendInput, build_psbt

SEED = bytes.fromhex("000102030405060708090a0b0c0d0e0f")
MASTER = MasterKey.from_seed(SEED)


def sample_body() -> dict:
    return {
        "nested": {"list": [1, "two", {"deep": True}], "int": 42},
        "unicode": "sats für agents — 日本語",
        "empty": {},
    }


@pytest.mark.parametrize("message_type", list(MessageType))
def test_payload_round_trips(message_type):
    payload = Payload(message_type, sample_body())
    assert decode(encode(payload)) == payload
    parts = to_qr_parts(payload, max_part_chars=200)
    assert from_qr_parts(parts) == payload
    shuffled = parts[:]
    random.Random(7).shuffle(shuffled)
    assert from_qr_parts(shuffled) == payload


@pytest.mark.parametrize(
    "text",
    [
        json.dumps({"v": 2, "t": "spend_plan", "b": {}}),
        json.dumps({"v": 1, "t": "no_such_type", "b": {}}),
        json.dumps({"v": 1, "t": "spend_plan", "b": [1, 2]}),
        json.dumps({"v": 1, "t": "spend_plan"}),
        json.dumps([1, 2, 3]),
        "definitely not json",
    ],
)
def test_decode_rejects_bad_payloads(text):
    with pytest.raises(ValueError):
        decode(text)


def big_psbt_payload() -> Payload:
    inputs = [
        SpendInput(
            txid=secrets.token_hex(32),
            vout=i % 4,
            amount_sats=100_000,
            public_key=MASTER.envelope(i).public_key,
        )
        for i in range(60)
    ]
    outputs = [Output(MASTER.receive(i).address, 50_000) for i in range(60)]
    change = Output(MASTER.change(0).address, 60 * 100_000 - 60 * 50_000 - 2_000)
    psbt = build_psbt(inputs, outputs, change)
    return Payload(MessageType.UNSIGNED_PSBT, {"psbt": psbt.to_string()})


def test_large_psbt_over_bbqr():
    payload_obj = big_psbt_payload()
    parts = to_qr_parts(payload_obj)
    assert len(parts) >= 3
    for i, part in enumerate(parts):
        assert part.startswith("B$")
        if i < len(parts) - 1:
            assert len(part) == len(parts[0])
            assert len(part[8:]) % 8 == 0
    assert from_qr_parts(parts[::-1]) == from_qr_parts(parts)
    payload = from_qr_parts(parts)
    reparsed = PSBT.from_string(payload.body["psbt"])
    original = PSBT.from_string(payload_obj.body["psbt"])
    assert reparsed.serialize() == original.serialize()


def test_render_payload_frames():
    frames = render_payload(big_psbt_payload(), kind="png")
    assert len(frames) >= 3
    assert all(f.startswith(b"\x89PNG") for f in frames)


def test_wrong_file_type_rejected():
    from satchel_core.qr import bbqr_split

    parts = bbqr_split(encode(Payload(MessageType.SPEND_PLAN, {})).encode(), "P")
    with pytest.raises(ValueError):
        from_qr_parts(parts)
