"""Ledger EIP-191 approval plans: validation, canonical text, and recovery."""

import base64
import hashlib
import re
import time
from datetime import datetime, timezone

from Crypto.Hash import keccak
from embit import script
from embit.psbt import PSBT
from embit.util import secp256k1

from satchel_core.keys import (
    HARDENED,
    Branch,
    MasterKey,
    parse_hardened_path,
)
from satchel_core.payloads import MessageType, Payload
from satchel_core.transactions import input_derivation, output_derivation

from .inventory import Inventory

MAX_SATS = 2_100_000_000_000_000
MAX_SPEND_FEE_SATS = 100_000
LEDGER_PATH = "44'/60'/0'/0/0"
NONCE_RE = re.compile(r"^[0-9a-f]{16}$")
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._-]{0,31}$")
DESTINATION_RE = re.compile(r"^bcrt1[02-9ac-hj-np-z]{8,87}$")
HASH_RE = re.compile(r"^[0-9a-f]{64}$")
MONTHS = (
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
)
SATCHEL_KEYS = {
    "kind",
    "satchel_index",
    "agent_id",
    "budget_sats",
    "expires_at",
    "psbt_sha256",
}
SPEND_KEYS = {"kind", "amount_sats", "destination", "purpose", "psbt_sha256"}
BODY_KEYS = {"plan", "text", "nonce", "signature", "address", "path"}
SIGNATURE_RE = re.compile(r"^0x[0-9a-f]{130}$")


class ApprovalRejected(ValueError):
    """The Ledger approval payload failed validation."""


class EnvelopeUnavailable(ApprovalRejected):
    """The requested satchel is already funded or assigned to an agent."""


def _check_int(value: object, name: str, lo: int, hi: int) -> None:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{name} must be an integer")
    if value < lo or value > hi:
        raise ValueError(f"{name} out of range")


def validate_plan(plan: object) -> dict:
    """Validate a plan's exact shape and ranges; returns the plan dict."""
    if not isinstance(plan, dict):
        raise ValueError("plan must be an object")
    kind = plan.get("kind")
    if kind == "satchel_grant":
        if set(plan) != SATCHEL_KEYS:
            raise ValueError("satchel grant has missing or extra keys")
        _check_int(plan["satchel_index"], "satchel_index", 0, 2**31 - 1)
        _check_int(plan["budget_sats"], "budget_sats", 1, MAX_SATS)
        _check_int(plan["expires_at"], "expires_at", 1, 253_402_300_740)
        if plan["expires_at"] % 60 != 0:
            raise ValueError("expires_at must be a multiple of 60")
        if not isinstance(plan["agent_id"], str) or not NAME_RE.fullmatch(
            plan["agent_id"]
        ):
            raise ValueError("invalid agent_id")
        if not isinstance(plan["psbt_sha256"], str) or not HASH_RE.fullmatch(
            plan["psbt_sha256"]
        ):
            raise ValueError("invalid psbt_sha256")
    elif kind == "large_spend":
        if set(plan) != SPEND_KEYS:
            raise ValueError("large spend has missing or extra keys")
        _check_int(plan["amount_sats"], "amount_sats", 1, MAX_SATS)
        if not isinstance(plan["destination"], str) or not DESTINATION_RE.fullmatch(
            plan["destination"]
        ):
            raise ValueError("invalid destination")
        script.address_to_scriptpubkey(plan["destination"])
        if not isinstance(plan["purpose"], str) or not NAME_RE.fullmatch(
            plan["purpose"]
        ):
            raise ValueError("invalid purpose")
        if not isinstance(plan["psbt_sha256"], str) or not HASH_RE.fullmatch(
            plan["psbt_sha256"]
        ):
            raise ValueError("invalid psbt_sha256")
    else:
        raise ValueError("unknown plan kind")
    return plan


def _format_btc(sats: int) -> str:
    integer, fraction = divmod(sats, 100_000_000)
    frac = f"{fraction:08d}".rstrip("0")
    return f"{integer}.{frac}" if frac else str(integer)


def _format_expiry(expires_at: int) -> str:
    dt = datetime.fromtimestamp(expires_at, tz=timezone.utc)
    return (
        f"{dt.day:02d} {MONTHS[dt.month - 1]} "
        f"{dt.hour:02d}:{dt.minute:02d}"
    )


def render_text(plan: dict, nonce: str) -> str:
    if plan["kind"] == "satchel_grant":
        # One approval covers both: fund the satchel from main funds and hand
        # its key to the agent.
        return (
            f"Create a {_format_btc(plan['budget_sats'])} BTC satchel "
            f"#{plan['satchel_index']} for {plan['agent_id']} from main "
            f"funds, expires {_format_expiry(plan['expires_at'])} UTC. "
            f"Nonce {nonce}"
        )
    dest = plan["destination"]
    return (
        f"Pay {_format_btc(plan['amount_sats'])} BTC to "
        f"{dest[:10]}...{dest[-6:]} for {plan['purpose']}, PSBT "
        f"{plan['psbt_sha256'][:8]}. Nonce {nonce}"
    )


def eip191_recover(text: str, signature_hex: str) -> str:
    """Recover the signer's Ethereum address from an EIP-191 signature."""
    if not isinstance(signature_hex, str) or not SIGNATURE_RE.fullmatch(
        signature_hex
    ):
        raise ValueError("signature must be 0x + 130 lowercase hex chars")
    sig = bytes.fromhex(signature_hex[2:])
    v = sig[64]
    if v in (27, 28):
        recid = v - 27
    elif v in (0, 1):
        recid = v
    else:
        raise ValueError(f"invalid recovery id {v}")
    msg = text.encode()
    prefix = b"\x19Ethereum Signed Message:\n" + str(len(msg)).encode()
    digest = keccak.new(digest_bits=256, data=prefix + msg).digest()
    rec_sig = secp256k1.ecdsa_recoverable_signature_parse_compact(sig[:64], recid)
    pub = secp256k1.ecdsa_recover(rec_sig, digest)
    raw = secp256k1.ec_pubkey_serialize(pub, secp256k1.EC_UNCOMPRESSED)
    address = keccak.new(digest_bits=256, data=raw[1:]).digest()[-20:]
    return "0x" + address.hex()


def _check_main_funds_psbt(
    master: MasterKey,
    fingerprint: str,
    psbt_bytes: bytes,
    *,
    psbt_sha256: str,
    destination: str,
    amount_sats: int,
) -> PSBT:
    """A main-funds PSBT: vault inputs, one exact payment, vault change only."""
    digest = hashlib.sha256(psbt_bytes).hexdigest()
    if digest != psbt_sha256:
        raise ApprovalRejected("PSBT does not match the approved hash")
    try:
        psbt = PSBT.parse(psbt_bytes)
    except Exception as exc:
        raise ApprovalRejected(f"cannot parse PSBT: {exc}") from exc
    tx = psbt.tx
    if len(tx.vin) != len(psbt.inputs) or len(tx.vout) != len(psbt.outputs):
        raise ApprovalRejected("PSBT scope count does not match transaction")
    total_in = 0
    for i, scope in enumerate(psbt.inputs):
        if scope.witness_utxo is None:
            raise ApprovalRejected(f"input {i} is missing witness_utxo")
        total_in += scope.witness_utxo.value
        try:
            derivation = input_derivation(psbt, i)
        except ValueError as exc:
            raise ApprovalRejected(f"input {i} derivation is invalid: {exc}") from exc
        if derivation is None:
            raise ApprovalRejected(f"input {i} has no vault derivation")
        pubkey, fingerprint_i, path_i = derivation
        if fingerprint_i != fingerprint:
            raise ApprovalRejected(f"input {i} is not derived from this vault")
        try:
            indexes = parse_hardened_path(path_i)
        except ValueError as exc:
            raise ApprovalRejected(f"input {i} has a bad path: {exc}") from exc
        if indexes[3] not in (
            Branch.RECEIVE | HARDENED,
            Branch.CHANGE | HARDENED,
        ):
            raise ApprovalRejected(f"input {i} is not a receive/change key")
        derived = master.derive(path_i)
        if derived.public_key != pubkey:
            raise ApprovalRejected(f"input {i} derivation does not match key")
        if (
            script.address_to_scriptpubkey(derived.address)
            != scope.witness_utxo.script_pubkey
        ):
            raise ApprovalRejected(
                f"input {i} derivation does not match its script"
            )
    approved_script = script.address_to_scriptpubkey(destination)
    payment_count = 0
    total_out = 0
    for i in range(len(psbt.outputs)):
        out = tx.vout[i]
        total_out += out.value
        if out.script_pubkey == approved_script:
            if out.value != amount_sats:
                raise ApprovalRejected(
                    "PSBT pays the destination the wrong amount"
                )
            payment_count += 1
            continue
        try:
            derivation = output_derivation(psbt, i)
        except ValueError as exc:
            raise ApprovalRejected(
                f"output {i} derivation is invalid: {exc}"
            ) from exc
        if derivation is None:
            raise ApprovalRejected(f"output {i} is a foreign output")
        pubkey, fingerprint_o, path_o = derivation
        if fingerprint_o != fingerprint:
            raise ApprovalRejected(f"output {i} is not derived from this vault")
        try:
            indexes = parse_hardened_path(path_o)
        except ValueError as exc:
            raise ApprovalRejected(f"output {i} has a bad path: {exc}") from exc
        if indexes[3] != Branch.CHANGE | HARDENED:
            raise ApprovalRejected(f"output {i} is not a vault change key")
        derived = master.derive(path_o)
        if derived.public_key != pubkey:
            raise ApprovalRejected(f"output {i} derivation does not match key")
        if (
            script.address_to_scriptpubkey(derived.address)
            != out.script_pubkey
        ):
            raise ApprovalRejected(
                f"output {i} derivation does not match its script"
            )
    if payment_count != 1:
        raise ApprovalRejected("PSBT must pay the destination exactly once")
    if total_in - total_out > MAX_SPEND_FEE_SATS:
        raise ApprovalRejected(
            f"fee {total_in - total_out} sats exceeds the {MAX_SPEND_FEE_SATS} cap"
        )
    return psbt


def validate_approval(
    approval: Payload,
    *,
    master: MasterKey,
    ledger_address: str,
    inventory: Inventory,
    unsigned_psbt: bytes | None = None,
    now: int | None = None,
) -> tuple[dict, PSBT | None]:
    """Validate a ledger_approval payload.

    Returns (plan, psbt), with the PSBT parsed from the validated bytes.
    Both kinds spend main funds, so both need the unsigned PSBT. Raises
    ApprovalRejected on any failure.
    """
    now = int(time.time()) if now is None else now
    if approval.type != MessageType.LEDGER_APPROVAL:
        raise ApprovalRejected("payload is not a ledger_approval")
    body = approval.body
    if set(body) != BODY_KEYS:
        raise ApprovalRejected("approval body has missing or extra keys")
    try:
        plan = validate_plan(body["plan"])
    except ValueError as exc:
        raise ApprovalRejected(f"invalid plan: {exc}") from exc
    nonce = body["nonce"]
    if not isinstance(nonce, str) or not NONCE_RE.fullmatch(nonce):
        raise ApprovalRejected("invalid nonce")
    if inventory.has_nonce(nonce):
        raise ApprovalRejected("nonce already used")
    if body["text"] != render_text(plan, nonce):
        raise ApprovalRejected("text does not match the canonical plan text")
    if body["path"] != LEDGER_PATH:
        raise ApprovalRejected("unexpected derivation path")
    if not isinstance(body["address"], str) or body[
        "address"
    ].lower() != ledger_address:
        raise ApprovalRejected("approval address is not the registered Ledger")
    try:
        recovered = eip191_recover(body["text"], body["signature"])
    except Exception as exc:
        raise ApprovalRejected(f"signature recovery failed: {exc}") from exc
    if recovered != ledger_address:
        raise ApprovalRejected(
            "signature does not recover to the registered Ledger"
        )
    if unsigned_psbt is None:
        raise ApprovalRejected("approval requires the unsigned PSBT")
    if plan["kind"] == "satchel_grant":
        if plan["expires_at"] <= now:
            raise ApprovalRejected("satchel grant has expired")
        index = plan["satchel_index"]
        if index >= len(inventory.envelopes):
            raise ApprovalRejected("satchel was never reserved")
        satchel = inventory.envelopes[index]
        if satchel.get("status") != "reserved" or satchel.get("assigned_to"):
            raise EnvelopeUnavailable("satchel is already funded or assigned")
        if satchel["budget_sats"] != plan["budget_sats"]:
            raise ApprovalRejected("budget does not match the reserved satchel")
        derived = master.envelope(index)
        if derived.address != satchel["address"]:
            raise ApprovalRejected("satchel address does not match its key")
        return plan, _check_main_funds_psbt(
            master,
            master.fingerprint,
            unsigned_psbt,
            psbt_sha256=plan["psbt_sha256"],
            destination=derived.address,
            amount_sats=plan["budget_sats"],
        )
    return plan, _check_main_funds_psbt(
        master,
        master.fingerprint,
        unsigned_psbt,
        psbt_sha256=plan["psbt_sha256"],
        destination=plan["destination"],
        amount_sats=plan["amount_sats"],
    )
