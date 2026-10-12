"""Tests for seed generation and the encrypted seed file."""

import json
import stat
import types

import pytest

import satchel_vault.seed as seed_mod
from satchel_vault.seed import (
    WrongPassphrase,
    generate_seed,
    read_seed_file,
    write_seed_file,
)

PASSPHRASE = "correct horse battery staple"
SEED = bytes(range(32))


@pytest.mark.parametrize(
    "dice",
    ["1" * 19, "0" * 25, "7" * 25, "12345a" * 5, "", "   "],
)
def test_dice_rejected(dice):
    with pytest.raises(ValueError):
        generate_seed(dice)


def test_dice_accepted():
    assert len(generate_seed("123456" * 5)) == 32


def test_dice_whitespace_stripped(monkeypatch):
    monkeypatch.setattr(
        seed_mod,
        "secrets",
        types.SimpleNamespace(token_bytes=lambda n: b"\x00" * n),
    )
    spaced = generate_seed("1 2 3 4 5 6 1 2 3 4 5 6 1 2 3 4 5 6 1 2")
    assert spaced == generate_seed("123456" * 3 + "12")


def test_seed_mixing(monkeypatch):
    monkeypatch.setattr(
        seed_mod,
        "secrets",
        types.SimpleNamespace(token_bytes=lambda n: b"\x00" * n),
    )
    fixed = generate_seed("1" * 25)
    assert generate_seed("1" * 25) == fixed
    assert generate_seed("2" * 25) != fixed
    monkeypatch.undo()
    assert generate_seed("1" * 25) != generate_seed("1" * 25)


def test_seed_file_round_trip(tmp_path):
    path = tmp_path / "seed.json"
    write_seed_file(path, SEED, PASSPHRASE)
    assert read_seed_file(path, PASSPHRASE) == SEED
    doc = json.loads(path.read_text())
    assert doc["kdf"]["name"] == "scrypt"
    assert doc["cipher"] == "aes-256-gcm"
    assert doc["fingerprint"]


def test_wrong_passphrase(tmp_path):
    path = tmp_path / "seed.json"
    write_seed_file(path, SEED, PASSPHRASE)
    with pytest.raises(WrongPassphrase):
        read_seed_file(path, "a different passphrase")


def test_tampered_ciphertext(tmp_path):
    path = tmp_path / "seed.json"
    write_seed_file(path, SEED, PASSPHRASE)
    doc = json.loads(path.read_text())
    raw = bytearray.fromhex(doc["ciphertext"])
    raw[0] ^= 1
    doc["ciphertext"] = raw.hex()
    path.write_text(json.dumps(doc))
    with pytest.raises(WrongPassphrase):
        read_seed_file(path, PASSPHRASE)


def test_seed_file_mode_and_no_seed_plaintext(tmp_path):
    path = tmp_path / "seed.json"
    write_seed_file(path, SEED, PASSPHRASE)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert SEED.hex() not in path.read_text()


def test_short_passphrase_rejected(tmp_path):
    with pytest.raises(ValueError):
        write_seed_file(tmp_path / "s.json", SEED, "short")
