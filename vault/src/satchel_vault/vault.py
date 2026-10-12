"""The vault: an air-gapped device holding the master seed. It never signs."""

from __future__ import annotations

import base64
import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path

from embit.psbt import PSBT

from satchel_core.events import emit
from satchel_core.keys import MasterKey
from satchel_core.payloads import MessageType, Payload

from . import release as release_mod
from . import seed as seed_store
from .approvals import ApprovalRejected
from .inventory import Inventory
from .verification import verify_transaction

SEED_FILE = "seed.json"
INVENTORY_FILE = "inventory.json"
MAX_EXPORT_COUNT = 100
MIN_ENVELOPE_BUDGET_SATS = 1_000
DEMO_ENVELOPE_BUDGETS = (100_000, 200_000, 500_000)


class VaultLocked(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class Vault:
    """Holds only a MasterKey in memory once unlocked; seed bytes are never kept."""

    def __init__(self, data_dir: str | Path):
        self.data_dir = Path(data_dir)
        self._master: MasterKey | None = None
        self._ledger_address: str | None = None
        self._release_lock = threading.Lock()
        self._seed_path = self.data_dir / SEED_FILE
        self._inventory_path = self.data_dir / INVENTORY_FILE

    @classmethod
    def from_env(cls) -> Vault:
        return cls(os.environ.get("SATCHEL_VAULT_DIR", ".satchel/vault"))

    def __repr__(self) -> str:
        state = (
            "unlocked"
            if self._master is not None
            else "initialized" if self.initialized else "uninitialized"
        )
        return f"Vault(fingerprint={self.fingerprint}, {state})"

    @property
    def initialized(self) -> bool:
        return self._seed_path.exists()

    @property
    def fingerprint(self) -> str | None:
        if self._master is not None:
            return self._master.fingerprint
        if self.initialized:
            return json.loads(self._seed_path.read_text()).get("fingerprint")
        return None

    def _require(self) -> MasterKey:
        if self._master is None:
            reason = "locked" if self.initialized else "uninitialized"
            raise VaultLocked(f"vault is {reason}")
        return self._master

    def _inventory(self) -> Inventory:
        return Inventory(self._inventory_path)

    def setup(self, dice: str, passphrase: str, ledger_address: str) -> str:
        if self.initialized:
            raise ValueError("vault already has a seed; reset first")
        seed = seed_store.generate_seed(dice)
        self._ledger_address = seed_store.check_ledger_address(ledger_address)
        seed_store.write_seed_file(
            self._seed_path, seed, passphrase, self._ledger_address
        )
        emit(
            "vault",
            "seed_created",
            f"seed created, fingerprint {self.fingerprint}, "
            f"ledger {self._ledger_address}",
            {"ledger_address": self._ledger_address},
        )
        return self.fingerprint

    def unlock(self, passphrase: str) -> None:
        try:
            raw, ledger_address = seed_store.unlock_seed_file(
                self._seed_path, passphrase
            )
        except seed_store.WrongPassphrase:
            emit("vault", "unlock_failed", "unlock failed")
            raise
        self._master = MasterKey.from_seed(raw)
        self._ledger_address = ledger_address
        emit(
            "vault",
            "vault_unlocked",
            f"vault unlocked, fingerprint {self._master.fingerprint}",
        )

    def export_receive_addresses(self, count: int) -> Payload:
        return self._export_addresses("receive", count)

    def export_change_addresses(self, count: int) -> Payload:
        return self._export_addresses("change", count)

    def _export_addresses(self, kind: str, count: int) -> Payload:
        master = self._require()
        if (
            isinstance(count, bool)
            or not isinstance(count, int)
            or not 1 <= count <= MAX_EXPORT_COUNT
        ):
            raise ValueError(f"count must be an integer in 1..{MAX_EXPORT_COUNT}")
        inventory = self._inventory()
        section = inventory.data[kind]
        derive = master.receive if kind == "receive" else master.change
        entries = []
        for index in range(section["next_index"], section["next_index"] + count):
            key = derive(index)
            entry = {
                "index": index,
                "path": key.path,
                "address": key.address,
                "public_key": key.public_key,
            }
            entries.append(entry)
            section["addresses"].append(
                {**entry, "exported_at": _now(), "used": False}
            )
        section["next_index"] += count
        inventory.save()
        emit(
            "vault",
            "addresses_exported",
            f"exported {count} {kind} addresses",
            {"kind": kind, "count": count},
        )
        return Payload(
            MessageType.ADDRESS_EXPORT,
            {
                "kind": kind,
                "fingerprint": self.fingerprint,
                "addresses": entries,
            },
        )

    def allocate_demo_envelopes(self, count_each: int = 1) -> Payload:
        master = self._require()
        total = count_each * len(DEMO_ENVELOPE_BUDGETS)
        if (
            isinstance(count_each, bool)
            or not isinstance(count_each, int)
            or not 1 <= count_each
            or total > MAX_EXPORT_COUNT
        ):
            raise ValueError(
                f"count_each must allocate at most "
                f"{MAX_EXPORT_COUNT} envelopes in total"
            )
        inventory = self._inventory()
        entries = []
        index = len(inventory.data["envelopes"])
        for budget_sats in DEMO_ENVELOPE_BUDGETS:
            for _ in range(count_each):
                key = master.envelope(index)
                entry = {
                    "index": index,
                    "path": key.path,
                    "address": key.address,
                    "public_key": key.public_key,
                    "budget_sats": budget_sats,
                    "assigned_to": None,
                }
                entries.append(entry)
                inventory.data["envelopes"].append(
                    {**entry, "allocated_at": _now()}
                )
                index += 1
        inventory.save()
        emit(
            "vault",
            "envelopes_allocated",
            f"allocated {total} demo envelopes",
            {
                "count_each": count_each,
                "budgets": list(DEMO_ENVELOPE_BUDGETS),
            },
        )
        return Payload(
            MessageType.ADDRESS_EXPORT,
            {
                "kind": "envelope",
                "fingerprint": self.fingerprint,
                "addresses": entries,
            },
        )

    def allocate_envelopes(self, count: int, budget_sats: int) -> Payload:
        master = self._require()
        if (
            isinstance(count, bool)
            or not isinstance(count, int)
            or not 1 <= count <= MAX_EXPORT_COUNT
        ):
            raise ValueError(f"count must be an integer in 1..{MAX_EXPORT_COUNT}")
        if (
            isinstance(budget_sats, bool)
            or not isinstance(budget_sats, int)
            or budget_sats < MIN_ENVELOPE_BUDGET_SATS
        ):
            raise ValueError(
                f"budget_sats must be an integer >= {MIN_ENVELOPE_BUDGET_SATS}"
            )
        inventory = self._inventory()
        entries = []
        for index in range(
            len(inventory.data["envelopes"]),
            len(inventory.data["envelopes"]) + count,
        ):
            key = master.envelope(index)
            entry = {
                "index": index,
                "path": key.path,
                "address": key.address,
                "public_key": key.public_key,
                "budget_sats": budget_sats,
                "assigned_to": None,
            }
            entries.append(entry)
            inventory.data["envelopes"].append({**entry, "allocated_at": _now()})
        inventory.save()
        emit(
            "vault",
            "envelopes_allocated",
            f"allocated {count} envelopes of {budget_sats} sats",
            {"count": count, "budget_sats": budget_sats},
        )
        return Payload(
            MessageType.ADDRESS_EXPORT,
            {
                "kind": "envelope",
                "fingerprint": self.fingerprint,
                "addresses": entries,
            },
        )

    def envelope_export(self) -> Payload:
        self._require()
        envelopes = self._inventory().data["envelopes"]
        entries = [
            {
                "index": e["index"],
                "path": e["path"],
                "address": e["address"],
                "public_key": e["public_key"],
                "budget_sats": e["budget_sats"],
                "assigned_to": e["assigned_to"],
            }
            for e in envelopes
        ]
        emit(
            "vault",
            "envelopes_exported",
            f"exported {len(entries)} envelopes",
            {"count": len(entries)},
        )
        return Payload(
            MessageType.ADDRESS_EXPORT,
            {
                "kind": "envelope",
                "fingerprint": self.fingerprint,
                "addresses": entries,
            },
        )

    def verify(self, psbt_payload: Payload, signed_payload: Payload) -> Payload:
        master = self._require()
        if psbt_payload.type != MessageType.UNSIGNED_PSBT:
            raise ValueError(
                f"expected unsigned_psbt, got {psbt_payload.type}"
            )
        if signed_payload.type != MessageType.SIGNED_TX:
            raise ValueError(
                f"expected signed_tx, got {signed_payload.type}"
            )
        encoded = psbt_payload.body.get("psbt")
        if not isinstance(encoded, str):
            raise ValueError("unsigned_psbt body needs a 'psbt' string")
        try:
            approved = PSBT.parse(base64.b64decode(encoded, validate=True))
        except Exception as exc:
            raise ValueError("'psbt' is not a valid base64 PSBT") from exc
        tx_hex = signed_payload.body.get("tx")
        if not isinstance(tx_hex, str):
            raise ValueError("signed_tx body needs a 'tx' hex string")
        result = verify_transaction(
            master, self.fingerprint, approved, tx_hex
        )
        emit(
            "vault",
            "verification_"
            + ("passed" if result["result"] == "pass" else "failed"),
            f"verification {result['result']} for {result['txid']}",
            {
                "txid": result["txid"],
                "reasons": [f["reason"] for f in result["failures"]],
            },
        )
        return Payload(MessageType.VERIFICATION_RESULT, result)

    def release_envelope(self, approval: Payload) -> Payload:
        master = self._require()
        emit("vault", "release_requested", "envelope release requested")
        try:
            with self._release_lock:
                released, plan = release_mod.release_envelope(
                    master,
                    self._inventory(),
                    self._ledger_address,
                    approval,
                )
        except ApprovalRejected as exc:
            emit(
                "vault",
                "release_refused",
                f"release refused: {exc}",
                {"reason": str(exc)},
            )
            raise
        emit(
            "vault",
            "envelope_released",
            f"envelope {plan['envelope_index']} released to "
            f"{plan['agent_id']}",
            {
                "envelope_index": plan["envelope_index"],
                "agent_id": plan["agent_id"],
                "nonce": approval.body["nonce"],
            },
        )
        return released

    def release_spend(self, approval: Payload, psbt_payload: Payload) -> Payload:
        master = self._require()
        emit("vault", "release_requested", "spend release requested")
        if psbt_payload.type != MessageType.UNSIGNED_PSBT:
            raise ValueError(
                f"expected unsigned_psbt, got {psbt_payload.type}"
            )
        encoded = psbt_payload.body.get("psbt")
        if not isinstance(encoded, str):
            raise ValueError("unsigned_psbt body needs a 'psbt' string")
        try:
            raw = base64.b64decode(encoded, validate=True)
            PSBT.parse(raw)
        except Exception as exc:
            raise ValueError("'psbt' is not a valid base64 PSBT") from exc
        try:
            with self._release_lock:
                released, plan = release_mod.release_spend(
                    master,
                    self._inventory(),
                    self._ledger_address,
                    approval,
                    raw,
                )
        except ApprovalRejected as exc:
            emit(
                "vault",
                "release_refused",
                f"release refused: {exc}",
                {"reason": str(exc)},
            )
            raise
        emit(
            "vault",
            "spend_keys_released",
            f"released {len(released.body['keys'])} input keys for "
            f"PSBT {plan['psbt_sha256'][:8]}",
            {
                "psbt_sha256": plan["psbt_sha256"],
                "paths": [k["path"] for k in released.body["keys"]],
                "nonce": approval.body["nonce"],
            },
        )
        return released

    def reset(self) -> None:
        for path in (self._seed_path, self._inventory_path):
            if path.exists():
                path.unlink()
        self._master = None
        emit("vault", "vault_reset", "vault reset")
