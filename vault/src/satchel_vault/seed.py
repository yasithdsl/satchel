"""Seed generation and encrypted at-rest storage for the vault."""

import json
import os
import secrets
import tempfile
from hashlib import sha256
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from satchel_core.keys import MasterKey

AAD = b"satchel-vault-seed-v1"
SCRYPT_PARAMS = {"n": 2**15, "r": 8, "p": 1}


class WrongPassphrase(ValueError):
    pass


def generate_seed(dice: str) -> bytes:
    """Mix operator dice rolls with system randomness into a 32-byte seed."""
    digits = "".join(dice.split())
    if (
        len(digits) < 20
        or not digits.isdigit()
        or any(c not in "123456" for c in digits)
    ):
        raise ValueError("dice must be at least 20 rolls, digits 1-6 only")
    return sha256(
        b"satchel/seed/v1" + secrets.token_bytes(32) + digits.encode()
    ).digest()


def _atomic_write(path: Path, text: str, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}-")
    try:
        with os.fdopen(fd, "w") as handle:
            handle.write(text)
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        os.unlink(tmp)
        raise


def write_seed_file(path: str | Path, seed: bytes, passphrase: str) -> None:
    path = Path(path)
    if len(passphrase) < 8:
        raise ValueError("passphrase must be at least 8 characters")
    salt = secrets.token_bytes(16)
    key = Scrypt(salt=salt, length=32, **SCRYPT_PARAMS).derive(passphrase.encode())
    nonce = secrets.token_bytes(12)
    doc = {
        "version": 1,
        "kdf": {"name": "scrypt", **SCRYPT_PARAMS, "salt": salt.hex()},
        "cipher": "aes-256-gcm",
        "nonce": nonce.hex(),
        "ciphertext": AESGCM(key).encrypt(nonce, seed, AAD).hex(),
        "fingerprint": MasterKey.from_seed(seed).fingerprint,
    }
    _atomic_write(path, json.dumps(doc))


def read_seed_file(path: str | Path, passphrase: str) -> bytes:
    doc = json.loads(Path(path).read_text())
    if doc.get("version") != 1 or doc.get("cipher") != "aes-256-gcm":
        raise ValueError("unsupported seed file format")
    kdf = doc["kdf"]
    if kdf.get("name") != "scrypt":
        raise ValueError("unsupported kdf")
    key = Scrypt(
        salt=bytes.fromhex(kdf["salt"]),
        length=32,
        n=kdf["n"],
        r=kdf["r"],
        p=kdf["p"],
    ).derive(passphrase.encode())
    try:
        return AESGCM(key).decrypt(
            bytes.fromhex(doc["nonce"]), bytes.fromhex(doc["ciphertext"]), AAD
        )
    except InvalidTag as exc:
        raise WrongPassphrase("wrong passphrase or corrupted seed file") from exc
