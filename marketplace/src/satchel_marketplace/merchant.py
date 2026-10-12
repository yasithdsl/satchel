"""The marketplace merchant's own wallet — a demo third party, never the vault."""

from decimal import Decimal

from satchel_core.regtest import RegtestNode, btc_to_sats


class MerchantWallet:
    def __init__(self, node: RegtestNode, name: str = "merchant"):
        self.node = node
        self.name = name

    def ensure(self) -> None:
        self.node.ensure_wallet(self.name)

    def new_address(self, label: str) -> str:
        return self.node.call(
            "getnewaddress", label, "bech32", wallet=self.name
        )

    def received_sats(self, address: str, minconf: int) -> int:
        amount = self.node.call(
            "getreceivedbyaddress", address, minconf, wallet=self.name
        )
        return btc_to_sats(Decimal(str(amount)))

    def txids(self, address: str) -> list[str]:
        entries = self.node.call(
            "listreceivedbyaddress", 0, False, True, address, wallet=self.name
        )
        txids: list[str] = []
        for entry in entries:
            txids.extend(entry.get("txids", []))
        return txids
