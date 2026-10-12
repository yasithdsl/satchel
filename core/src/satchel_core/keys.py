"""Fully hardened HD key derivation for the Satchel wallet (regtest only)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import IntEnum

from embit import bip32, script
from embit.hashes import hash160
from embit.networks import NETWORKS

HARDENED = 0x80000000
PURPOSE = 84
COIN_TYPE = 1
ACCOUNT = 0
NETWORK = NETWORKS["regtest"]


class Branch(IntEnum):
    RECEIVE = 0
    CHANGE = 1
    ENVELOPE = 2


class NonHardenedPathError(ValueError):
    pass


def parse_hardened_path(path: str) -> list[int]:
    """Validate m/84'/1'/0'/{0,1,2}'/i' and return the hardened indexes.

    Every level must be hardened; the vault uses this to check paths in plans.
    """
    if not isinstance(path, str):
        raise ValueError(f"path must be a string, got {path!r}")
    steps = path.split("/")
    if steps[0] not in ("m", "M") or len(steps) < 2:
        raise ValueError(f"invalid derivation path: {path!r}")
    indexes = []
    for level, step in enumerate(steps[1:], start=1):
        if not step.endswith(("'", "h", "H")):
            raise NonHardenedPathError(
                f"level {level} of {path!r} is not hardened: {step!r}"
            )
        if not re.fullmatch(r"0|[1-9][0-9]*", step[:-1]):
            raise ValueError(f"invalid level {level} in path {path!r}: {step!r}")
        index = int(step[:-1])
        if not 0 <= index < HARDENED:
            raise ValueError(f"level {level} index out of range in {path!r}")
        indexes.append(index)
    if (
        len(indexes) != 5
        or indexes[0] != PURPOSE
        or indexes[1] != COIN_TYPE
        or indexes[2] != ACCOUNT
        or indexes[3] not in (Branch.RECEIVE, Branch.CHANGE, Branch.ENVELOPE)
    ):
        raise ValueError(
            f"path must match m/{PURPOSE}'/{COIN_TYPE}'/{ACCOUNT}'/{{0,1,2}}'/i': {path!r}"
        )
    return [i | HARDENED for i in indexes]


@dataclass(frozen=True)
class DerivedKey:
    path: str
    wif: str = field(repr=False)
    public_key: str
    address: str


class MasterKey:
    """Root HD key; derives only fully hardened m/84'/1'/0'/branch'/index' keys."""

    def __init__(self, root: bip32.HDKey):
        self._root = root

    @classmethod
    def from_seed(cls, seed: bytes, network: str = "regtest") -> MasterKey:
        if network != "regtest":
            raise ValueError(f"only regtest is supported, got {network!r}")
        if not 16 <= len(seed) <= 64:
            raise ValueError(f"seed must be 16..64 bytes, got {len(seed)}")
        return cls(bip32.HDKey.from_seed(seed, version=NETWORK["xprv"]))

    def __repr__(self) -> str:
        return f"MasterKey(fingerprint={self.fingerprint})"

    @property
    def fingerprint(self) -> str:
        return hash160(self._root.key.sec()).hex()[:8]

    def derive(self, path: str) -> DerivedKey:
        indexes = parse_hardened_path(path)
        node = self._root.derive(indexes)
        canonical = "m/" + "/".join(f"{i & ~HARDENED}'" for i in indexes)
        public_key = node.key.get_public_key()
        return DerivedKey(
            path=canonical,
            wif=node.key.wif(NETWORK),
            public_key=public_key.sec().hex(),
            address=script.p2wpkh(public_key).address(NETWORK),
        )

    def _derive(self, branch: Branch, index: int) -> DerivedKey:
        if (
            not isinstance(index, int)
            or isinstance(index, bool)
            or not 0 <= index < HARDENED
        ):
            raise ValueError(f"index must be an integer in 0..2^31-1, got {index!r}")
        return self.derive(f"m/{PURPOSE}'/{COIN_TYPE}'/{ACCOUNT}'/{int(branch)}'/{index}'")

    def receive(self, index: int) -> DerivedKey:
        return self._derive(Branch.RECEIVE, index)

    def change(self, index: int) -> DerivedKey:
        return self._derive(Branch.CHANGE, index)

    def envelope(self, index: int) -> DerivedKey:
        return self._derive(Branch.ENVELOPE, index)
