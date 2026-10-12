"""End-to-end envelope funding against regtest."""

import pytest
from fastapi.testclient import TestClient

from satchel_laptop.envelopes import envelope_statuses
from satchel_laptop.funding import fund_envelopes
from satchel_laptop.state import LaptopState
from satchel_laptop.vault_client import VaultClient
from satchel_vault.app import create_app as create_vault_app
from satchel_vault.vault import Vault

DICE = "1" * 25
PASSPHRASE = "correct horse battery staple"
LEDGER = "0xdad77910dbdfde764fc21fcd4e74d71bbaca6d8d"


@pytest.mark.regtest
def test_fund_envelopes_end_to_end(node, tmp_path):
    vault = Vault(tmp_path / "vault")
    vault.setup(DICE, PASSPHRASE, LEDGER)
    vault.unlock(PASSPHRASE)
    vault.allocate_envelopes(3, 50_000)
    client = VaultClient(http=TestClient(create_vault_app(vault)))
    state = LaptopState(tmp_path / "laptop" / "state.json")

    funded = fund_envelopes(client, node, state)
    assert len(funded) == 3
    assert [f["index"] for f in funded] == [0, 1, 2]

    statuses = envelope_statuses(client.fetch_envelopes(), node, state)
    assert [s.status for s in statuses] == ["unassigned"] * 3
    assert all(s.balance_sats == 50_000 and s.utxo_count == 1 for s in statuses)

    assert fund_envelopes(client, node, state) == []

    vault.allocate_envelopes(1, 50_000)
    statuses = envelope_statuses(client.fetch_envelopes(), node, state)
    assert statuses[-1].index == 3
    assert statuses[-1].status == "unfunded"
    assert statuses[-1].balance_sats == 0
