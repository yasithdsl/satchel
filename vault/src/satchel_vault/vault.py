"""The vault: an air-gapped device holding the master seed. It never signs."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from satchel_core.events import emit
from satchel_core.keys import MasterKey
from satchel_core.payloads import MessageType, Payload

from . import seed as seed_store
from .inventory import Inventory

SEED_FILE = "seed.json"
INVENTORY_FILE = "inventory.json"
MAX_EXPORT_COUNT = 100
MIN_ENVELOPE_BUDGET_SATS = 1_000


class VaultLocked(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class Vault:
    """Holds only a MasterKey in memory once unlocked; seed bytes are never kept."""

    def __init__(self, data_dir: str | Path):
        self.data_dir = Path(data_dir)
        self._master: MasterKey | None = None
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

    def setup(self, dice: str, passphrase: str) -> str:
        if self.initialized:
            raise ValueError("vault already has a seed; reset first")
        seed = seed_store.generate_seed(dice)
        seed_store.write_seed_file(self._seed_path, seed, passphrase)
        emit("vault", "seed_created", f"seed created, fingerprint {self.fingerprint}")
        return self.fingerprint

    def unlock(self, passphrase: str) -> None:
        try:
            raw = seed_store.read_seed_file(self._seed_path, passphrase)
        except seed_store.WrongPassphrase:
            emit("vault", "unlock_failed", "unlock failed")
            raise
        self._master = MasterKey.from_seed(raw)
        emit(
            "vault",
            "vault_unlocked",
            f"vault unlocked, fingerprint {self._master.fingerprint}",
        )

    def export_receive_addresses(self, count: int) -> Payload:
        master = self._require()
        if (
            isinstance(count, bool)
            or not isinstance(count, int)
            or not 1 <= count <= MAX_EXPORT_COUNT
        ):
            raise ValueError(f"count must be an integer in 1..{MAX_EXPORT_COUNT}")
        inventory = self._inventory()
        receive = inventory.data["receive"]
        entries = []
        for index in range(receive["next_index"], receive["next_index"] + count):
            key = master.receive(index)
            entry = {
                "index": index,
                "path": key.path,
                "address": key.address,
                "public_key": key.public_key,
            }
            entries.append(entry)
            receive["addresses"].append(
                {**entry, "exported_at": _now(), "used": False}
            )
        receive["next_index"] += count
        inventory.save()
        emit(
            "vault",
            "addresses_exported",
            f"exported {count} receive addresses",
            {"kind": "receive", "count": count},
        )
        return Payload(
            MessageType.ADDRESS_EXPORT,
            {
                "kind": "receive",
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

    def reset(self) -> None:
        for path in (self._seed_path, self._inventory_path):
            if path.exists():
                path.unlink()
        self._master = None
        emit("vault", "vault_reset", "vault reset")
