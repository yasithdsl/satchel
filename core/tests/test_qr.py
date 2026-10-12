"""Tests for BBQr split/join and QR frame rendering."""

import base64
import random
import secrets

import pytest
import segno

from satchel_core.qr import bbqr_join, bbqr_split, render_frames, render_qr

ALNUM = set("0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ $%*+-./:")


def test_split_join_round_trip_compressed():
    data = "".join(secrets.token_hex(16) for _ in range(200)).encode()
    parts = bbqr_split(data)
    assert len(parts) > 1
    assert parts[0][2] == "Z"
    assert bbqr_join(parts) == ("J", data)


def test_random_data_uses_base32_encoding():
    raw = secrets.token_bytes(2000)
    parts = bbqr_split(raw)
    assert parts[0][2] == "2"
    assert bbqr_join(parts) == ("J", raw)


def test_single_part_is_still_bbqr():
    parts = bbqr_split(b"tiny")
    assert len(parts) == 1
    assert parts[0].startswith("B$")
    assert bbqr_join(parts) == ("J", b"tiny")


def test_part_shape_and_alnum_charset():
    parts = bbqr_split(secrets.token_bytes(5000), max_part_chars=600)
    assert len(parts) > 3
    for i, part in enumerate(parts):
        assert part.startswith("B$")
        assert set(part) <= ALNUM
        assert part[3] == "J"
        if i < len(parts) - 1:
            assert len(part) == len(parts[0])
            assert len(part[8:]) % 8 == 0
        assert len(part) <= 600


def test_join_tolerates_shuffle_and_duplicates():
    raw = secrets.token_bytes(800)
    parts = bbqr_split(raw, max_part_chars=400)
    assert len(parts) >= 3
    shuffled = parts[2:] + parts[:2] + [parts[1]]
    assert bbqr_join(shuffled) == ("J", raw)


def test_join_rejects_bad_series():
    parts = bbqr_split(b"some data " * 50)
    with pytest.raises(ValueError):
        bbqr_join(parts[:-1])
    with pytest.raises(ValueError):
        bbqr_join(["not-a-part"])
    other = bbqr_split(b"different sized payload here " * 30)
    with pytest.raises(ValueError):
        bbqr_join(parts + [other[0]])


def test_join_handbuilt_hex_series():
    data = b"hello world"
    hexed = data.hex()
    parts = [f"B$HT0200{hexed[:8]}", f"B$HT0201{hexed[8:]}"]
    assert bbqr_join(parts) == ("T", data)


def test_join_handbuilt_base32_series():
    data = b"raw uncompressed bytes"
    encoded = base64.b32encode(data).decode().rstrip("=")
    parts = [f"B$2P0200{encoded[:8]}", f"B$2P0201{encoded[8:]}"]
    assert bbqr_join(parts[::-1]) == ("P", data)


def test_too_many_parts_and_tiny_part_size():
    with pytest.raises(ValueError):
        bbqr_split(secrets.token_bytes(6500), max_part_chars=16)
    with pytest.raises(ValueError):
        bbqr_split(b"x", max_part_chars=15)


def test_render_png_and_svg():
    png = render_qr("B$2J0100AAAA", kind="png")
    assert png.startswith(b"\x89PNG")
    svg = render_qr("B$2J0100AAAA", kind="svg")
    assert b"<svg" in svg


def test_frames_share_qr_version():
    parts = bbqr_split(secrets.token_bytes(3000), max_part_chars=400)
    version = segno.make(max(parts, key=len), error="l", micro=False).version
    for part in parts:
        qr = segno.make(part, error="l", micro=False, version=version)
        assert qr.version == version
    frames = render_frames(parts, kind="png")
    assert len(frames) == len(parts)
    assert all(f.startswith(b"\x89PNG") for f in frames)
