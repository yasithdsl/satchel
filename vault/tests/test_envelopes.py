"""Satchel inventory export on the vault."""

import os
from pathlib import Path

from fastapi.testclient import TestClient

from satchel_core.keys import MasterKey
from satchel_core.payloads import MessageType, from_http
from satchel_vault.app import create_app
from satchel_vault.seed import read_seed_file

from .test_vault import PASSPHRASE, make_vault


def test_export_lists_every_reserved_satchel_publicly(tmp_path):
    vault = make_vault(tmp_path)
    vault.reserve_satchel(50_000)
    vault.reserve_satchel(60_000)
    payload = vault.envelope_export()
    assert payload.type == MessageType.ADDRESS_EXPORT
    assert payload.body["kind"] == "envelope"
    master = MasterKey.from_seed(
        read_seed_file(tmp_path / "vault" / "seed.json", PASSPHRASE)
    )
    entries = payload.body["addresses"]
    assert [e["index"] for e in entries] == [0, 1]
    assert [e["budget_sats"] for e in entries] == [50_000, 60_000]
    for entry in entries:
        assert entry["address"] == master.envelope(entry["index"]).address
        assert entry["assigned_to"] is None
        assert "wif" not in entry


def test_export_endpoint_and_events(tmp_path):
    vault = make_vault(tmp_path)
    for _ in range(3):
        vault.reserve_satchel(50_000)
    client = TestClient(create_app(vault))
    payload = from_http(client.get("/envelopes/export").json())
    assert len(payload.body["addresses"]) == 3
    log = Path(os.environ["SATCHEL_EVENT_LOG"]).read_text()
    assert '"satchel_reserved"' in log
    assert '"envelopes_exported"' in log


def test_repeated_exports_emit_one_event_until_something_changes(tmp_path):
    """The x-ray polls this export; polling must not flood the event stream."""
    vault = make_vault(tmp_path)
    vault.reserve_satchel(50_000)
    log_path = Path(os.environ["SATCHEL_EVENT_LOG"])

    def exported() -> int:
        return log_path.read_text().count('"envelopes_exported"')

    before = exported()
    for _ in range(5):
        vault.envelope_export()
    assert exported() == before + 1
    vault.reserve_satchel(60_000)
    vault.envelope_export()
    vault.envelope_export()
    assert exported() == before + 2
