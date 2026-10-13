"""Versioned JSON payloads that cross device boundaries (QR-ready)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Iterable

from .qr import bbqr_join, bbqr_split, render_frames

VERSION = 1


class MessageType(StrEnum):
    ADDRESS_EXPORT = "address_export"
    SPEND_PLAN = "spend_plan"
    LEDGER_APPROVAL = "ledger_approval"
    KEY_RELEASE = "key_release"
    UNSIGNED_PSBT = "unsigned_psbt"
    SIGNED_TX = "signed_tx"
    VERIFICATION_RESULT = "verification_result"
    FUNDING_PROOF = "funding_proof"


@dataclass(frozen=True)
class Payload:
    type: MessageType
    body: dict


def encode(payload: Payload) -> str:
    return json.dumps(
        {"v": VERSION, "t": payload.type.value, "b": payload.body},
        separators=(",", ":"),
        sort_keys=True,
    )


def decode(text: str) -> Payload:
    try:
        obj = json.loads(text)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"payload is not valid JSON: {exc}") from exc
    if not isinstance(obj, dict):
        raise ValueError("payload must be a JSON object")
    if obj.get("v") != VERSION:
        raise ValueError(f"unsupported payload version: {obj.get('v')!r}")
    try:
        message_type = MessageType(obj.get("t"))
    except ValueError:
        raise ValueError(f"unknown message type: {obj.get('t')!r}")
    if not isinstance(obj.get("b"), dict):
        raise ValueError("payload body must be a JSON object")
    return Payload(type=message_type, body=obj["b"])


def to_qr_parts(payload: Payload, max_part_chars: int = 1000) -> list[str]:
    return bbqr_split(encode(payload).encode(), "J", max_part_chars)


def from_qr_parts(parts: Iterable[str]) -> Payload:
    file_type, data = bbqr_join(parts)
    if file_type != "J":
        raise ValueError(f"expected file type J, got {file_type!r}")
    return decode(data.decode())


def render_payload(
    payload: Payload, kind: str = "svg", scale: int = 4, max_part_chars: int = 1000
) -> list[bytes]:
    return render_frames(to_qr_parts(payload, max_part_chars), kind, scale)


def to_http(payload: Payload) -> dict:
    return {
        "type": payload.type.value,
        "payload": encode(payload),
        "parts": to_qr_parts(payload),
    }


def from_http(obj: dict) -> Payload:
    """Rebuild a Payload from an HTTP body, verifying parts and payload agree."""
    if not isinstance(obj, dict):
        raise ValueError("http body must be an object")
    parts = obj.get("parts")
    if not isinstance(parts, list) or not all(isinstance(p, str) for p in parts):
        raise ValueError("http body must contain a list of QR parts")
    scanned = from_qr_parts(parts)
    if obj.get("payload") is not None and decode(obj["payload"]) != scanned:
        raise ValueError("payload field does not match the QR parts")
    return scanned
