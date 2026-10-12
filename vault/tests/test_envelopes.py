"""Envelope allocation and export on the vault."""

import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from satchel_core.keys import MasterKey
from satchel_core.payloads import MessageType, from_http
from satchel_vault.app import create_app
from satchel_vault.seed import read_seed_file

from .test_vault import DICE, PASSPHRASE, make_vault


def test_allocate_continues_indices_and_matches_master(tmp_path):
    vault = make_vault(tmp_path)
    first = vault.allocate_envelopes(2, 50_000)
    second = vault.allocate_envelopes(1, 75_000)
    assert first.type == MessageType.ADDRESS_EXPORT
    assert first.body["kind"] == "envelope"
    assert [a["index"] for a in first.body["addresses"]] == [0, 1]
    assert [a["index"] for a in second.body["addresses"]] == [2]
    master = MasterKey.from_seed(
        read_seed_file(tmp_path / "vault" / "seed.json", PASSPHRASE)
    )
    for entry in first.body["addresses"] + second.body["addresses"]:
        key = master.envelope(entry["index"])
        assert entry["address"] == key.address
        assert entry["public_key"] == key.public_key
        assert entry["path"] == key.path
        assert entry["assigned_to"] is None
        assert "wif" not in entry
    assert [a["budget_sats"] for a in first.body["addresses"]] == [50_000, 50_000]
    assert second.body["addresses"][0]["budget_sats"] == 75_000
    inventory = json.loads((tmp_path / "vault" / "inventory.json").read_text())
    assert len(inventory["envelopes"]) == 3


@pytest.mark.parametrize("count,budget", [(0, 50_000), (101, 50_000), (True, 50_000), (1, 999), (1, 0), (1, True), (1, "50000")])
def test_allocate_validation(tmp_path, count, budget):
    vault = make_vault(tmp_path)
    with pytest.raises(ValueError):
        vault.allocate_envelopes(count, budget)


def test_envelope_export_returns_all(tmp_path):
    vault = make_vault(tmp_path)
    vault.allocate_envelopes(2, 50_000)
    vault.allocate_envelopes(1, 60_000)
    payload = vault.envelope_export()
    assert payload.body["kind"] == "envelope"
    assert len(payload.body["addresses"]) == 3


def test_export_endpoint_and_events(tmp_path):
    vault = make_vault(tmp_path)
    vault.allocate_envelopes(3, 50_000)
    client = TestClient(create_app(vault))
    payload = from_http(client.get("/envelopes/export").json())
    assert len(payload.body["addresses"]) == 3
    log = Path(os.environ["SATCHEL_EVENT_LOG"]).read_text()
    assert '"envelopes_allocated"' in log
    assert '"envelopes_exported"' in log


def test_allocate_demo_envelopes(tmp_path):
    vault = make_vault(tmp_path)
    payload = vault.allocate_demo_envelopes()
    assert payload.type == MessageType.ADDRESS_EXPORT
    assert payload.body["kind"] == "envelope"
    entries = payload.body["addresses"]
    assert [e["budget_sats"] for e in entries] == [
        100_000,
        200_000,
        500_000,
    ]
    assert [e["index"] for e in entries] == [0, 1, 2]
    master = MasterKey.from_seed(
        read_seed_file(tmp_path / "vault" / "seed.json", PASSPHRASE)
    )
    for entry in entries:
        assert entry["address"] == master.envelope(entry["index"]).address

    more = vault.allocate_demo_envelopes(2)
    assert [e["budget_sats"] for e in more.body["addresses"]] == [
        100_000,
        100_000,
        200_000,
        200_000,
        500_000,
        500_000,
    ]
    assert [e["index"] for e in more.body["addresses"]] == list(range(3, 9))
    with pytest.raises(ValueError):
        vault.allocate_demo_envelopes(0)
    with pytest.raises(ValueError):
        vault.allocate_demo_envelopes(True)
