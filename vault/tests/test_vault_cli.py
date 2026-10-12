"""CLI and event-log checks for the vault."""

import json
import os
from pathlib import Path

import pytest

from satchel_core.keys import MasterKey
from satchel_vault.cli import main
from satchel_vault.seed import read_seed_file

from .test_vault import DICE, PASSPHRASE, make_vault


def test_cli_setup_and_reset(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("SATCHEL_VAULT_DIR", str(tmp_path / "vault"))
    monkeypatch.setenv("SATCHEL_VAULT_PASSPHRASE", PASSPHRASE)
    main(["setup", "--dice", DICE])
    out = capsys.readouterr().out
    assert "fingerprint" in out
    assert (tmp_path / "vault" / "seed.json").exists()
    with pytest.raises(SystemExit):
        main(["reset"])
    assert (tmp_path / "vault" / "seed.json").exists()
    main(["reset", "--yes"])
    assert not (tmp_path / "vault" / "seed.json").exists()


def test_events_have_no_secrets(tmp_path):
    log_path = Path(os.environ["SATCHEL_EVENT_LOG"])
    vault = make_vault(tmp_path)
    seed = read_seed_file(tmp_path / "vault" / "seed.json", PASSPHRASE)
    master = MasterKey.from_seed(seed)
    vault.export_receive_addresses(2)
    vault.reset()
    types = [
        json.loads(line)["type"] for line in log_path.read_text().splitlines()
    ]
    assert {
        "seed_created",
        "vault_unlocked",
        "addresses_exported",
        "vault_reset",
    } <= set(types)
    text = log_path.read_text()
    for secret in [seed.hex(), master.receive(0).wif, PASSPHRASE, DICE]:
        assert secret not in text
