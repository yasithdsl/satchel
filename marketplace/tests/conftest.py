"""Shared stub merchant for marketplace tests."""

import pytest

from satchel_marketplace.store import Store
from satchel_marketplace.catalogue import Catalogue


class StubMerchant:
    """Scripted merchant: received amounts and txids per address."""

    def __init__(self):
        self._next = 0
        self.confirmed: dict[str, int] = {}
        self.seen: dict[str, int] = {}
        self._txids: dict[str, list[str]] = {}

    def new_address(self, label: str) -> str:
        self._next += 1
        return f"bcrt1qmerchant{self._next:04d}"

    def received_sats(self, address: str, minconf: int) -> int:
        if minconf:
            return self.confirmed.get(address, 0)
        return self.seen.get(address, 0)

    def txids(self, address: str) -> list[str]:
        return list(self._txids.get(address, []))


@pytest.fixture
def merchant():
    return StubMerchant()


@pytest.fixture
def make_store(merchant):
    def build(tmp_path, clock=None):
        return Store(
            Catalogue.load(),
            merchant,
            data_dir=tmp_path / "marketplace",
            clock=clock,
        )

    return build
