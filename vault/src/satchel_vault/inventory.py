"""Persistent inventory of exported receive addresses and envelopes."""

import json
import os
import tempfile
from pathlib import Path

EMPTY = {
    "version": 1,
    "receive": {"next_index": 0, "addresses": []},
    "envelopes": [],
    "used_nonces": [],
}


class Inventory:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        if self.path.exists():
            self.data = json.loads(self.path.read_text())
            self.data.setdefault("used_nonces", [])
            for envelope in self.data["envelopes"]:
                envelope.setdefault("assigned_to", None)
        else:
            self.data = json.loads(json.dumps(EMPTY))

    @property
    def envelopes(self) -> list:
        return self.data["envelopes"]

    @property
    def used_nonces(self) -> list:
        return self.data["used_nonces"]

    def has_nonce(self, nonce: str) -> bool:
        return nonce in self.data["used_nonces"]

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
