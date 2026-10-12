"""Local persistent state for the laptop coordinator."""

import json
import os
import tempfile
from pathlib import Path

EMPTY = {"version": 1, "funding": {}}


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
