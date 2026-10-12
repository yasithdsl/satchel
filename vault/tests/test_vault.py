"""Tests for the Vault device object."""

import json
import os
from pathlib import Path

import pytest

from satchel_core.keys import MasterKey
from satchel_core.payloads import MessageType
from satchel_vault.seed import WrongPassphrase, read_seed_file
from satchel_vault.vault import Vault, VaultLocked

DICE = "1" * 25
PASSPHRASE = "correct horse battery staple"
LEDGER = "0xdad77910dbdfde764fc21fcd4e74d71bbaca6d8d"


def make_vault(tmp_path: Path, unlock: bool = True) -> Vault:
    vault = Vault(tmp_path / "vault")
    vault.setup(DICE, PASSPHRASE, LEDGER)
    if unlock:
        vault.unlock(PASSPHRASE)
    return vault


def event_types() -> list[str]:
    path = Path(os.environ["SATCHEL_EVENT_LOG"])
    return [json.loads(line)["type"] for line in path.read_text().splitlines()]


def test_setup_twice_refused(tmp_path):
    make_vault(tmp_path)
    vault = Vault(tmp_path / "vault")
    with pytest.raises(ValueError):
        vault.setup(DICE, PASSPHRASE, LEDGER)


def test_unlock_wrong_passphrase_emits_event(tmp_path):
    vault = make_vault(tmp_path, unlock=False)
    with pytest.raises(WrongPassphrase):
        vault.unlock("not the passphrase")
    assert vault._master is None
    assert "unlock_failed" in event_types()


def test_export_continues_indices(tmp_path):
    vault = make_vault(tmp_path)
    first = vault.export_receive_addresses(5)
    second = vault.export_receive_addresses(3)
    assert first.type == MessageType.ADDRESS_EXPORT
    assert first.body["kind"] == "receive"
    assert [a["index"] for a in first.body["addresses"]] == [0, 1, 2, 3, 4]
    assert [a["index"] for a in second.body["addresses"]] == [5, 6, 7]
    master = MasterKey.from_seed(
        read_seed_file(tmp_path / "vault" / "seed.json", PASSPHRASE)
    )
    for entry in first.body["addresses"] + second.body["addresses"]:
        key = master.receive(entry["index"])
        assert entry["address"] == key.address
        assert entry["public_key"] == key.public_key
        assert entry["path"] == key.path
    inventory = json.loads((tmp_path / "vault" / "inventory.json").read_text())
    assert inventory["receive"]["next_index"] == 8
    assert len(inventory["receive"]["addresses"]) == 8
    assert all(a["used"] is False for a in inventory["receive"]["addresses"])
    assert all("wif" not in a for a in first.body["addresses"])


def test_export_count_bounds(tmp_path):
    vault = make_vault(tmp_path)
    for bad in (0, 101, -1, True, 2.5, "3"):
        with pytest.raises(ValueError):
            vault.export_receive_addresses(bad)


def test_reset_removes_files(tmp_path):
    vault = make_vault(tmp_path)
    vault.export_receive_addresses(1)
    vault.reset()
    assert not (tmp_path / "vault" / "seed.json").exists()
    assert not (tmp_path / "vault" / "inventory.json").exists()
    assert not vault.initialized
    assert vault.fingerprint is None
    assert "vault_reset" in event_types()


def test_locked_and_uninitialized_raise(tmp_path):
    fresh = Vault(tmp_path / "vault")
    with pytest.raises(VaultLocked):
        fresh.export_receive_addresses(1)
    fresh.setup(DICE, PASSPHRASE, LEDGER)
    with pytest.raises(VaultLocked):
        fresh.export_receive_addresses(1)


def test_repr_hides_secrets(tmp_path):
    vault = make_vault(tmp_path)
    master = MasterKey.from_seed(
        read_seed_file(tmp_path / "vault" / "seed.json", PASSPHRASE)
    )
    assert master.receive(0).wif not in repr(vault)
    assert PASSPHRASE not in repr(vault)
