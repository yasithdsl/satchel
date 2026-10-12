"""Local persistent state for the laptop coordinator."""

import json
import os
import tempfile
from pathlib import Path

EMPTY = {"version": 1, "funding": {}, "main_funds": None}


class LaptopState:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        if self.path.exists():
            self.data = json.loads(self.path.read_text())
        else:
            self.data = json.loads(json.dumps(EMPTY))

    @classmethod
    def from_env(cls) -> "LaptopState":
        directory = Path(os.environ.get("SATCHEL_LAPTOP_DIR", ".satchel/laptop"))
        return cls(directory / "state.json")

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=f".{self.path.name}-")
        try:
            with os.fdopen(fd, "w") as handle:
                json.dump(self.data, handle, indent=1)
            os.replace(tmp, self.path)
        except BaseException:
            os.unlink(tmp)
            raise

    @property
    def funding(self) -> dict:
        return self.data["funding"]

    def record_funding(self, address: str, txid: str, vout: int, amount_sats: int) -> None:
        self.data["funding"].setdefault(address, []).append(
            {"txid": txid, "vout": vout, "amount_sats": amount_sats}
        )
        self.save()

    def funding_for(self, address: str) -> list[dict]:
        return self.data["funding"].get(address, [])

    @property
    def main_funds(self) -> dict | None:
        self.data.setdefault("main_funds", None)
        return self.data["main_funds"]

    def add_main_funds(
        self,
        fingerprint: str,
        entries: list[dict],
    ) -> None:
        """Record exported main-fund addresses (public data only).

        Resets the address list if the fingerprint changes (a different vault).
        """
        self.data.setdefault("main_funds", None)
        if (
            self.data["main_funds"] is None
            or self.data["main_funds"]["fingerprint"] != fingerprint
        ):
            self.data["main_funds"] = {"fingerprint": fingerprint, "addresses": []}
        self.data["main_funds"]["addresses"].extend(
            {
                "kind": e["kind"],
                "index": e["index"],
                "path": e["path"],
                "address": e["address"],
                "public_key": e["public_key"],
            }
            for e in entries
        )
        self.save()

    def main_fund_entries(self) -> list[dict]:
        funds = self.main_funds
        if not funds:
            return []
        return list(funds["addresses"])
