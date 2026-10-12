"""BBQr encoding/decoding and QR frame rendering.

BBQr (https://github.com/coinkite/BBQr) splits a payload into fixed-size
alphanumeric parts, each framed by an 8-char header:
B$ + encoding + file_type + total + index (last two as 2-digit base36).
"""

import base64
import io
import zlib
from typing import Iterable

import segno

B36 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
HEADER_LEN = 8
MAX_PARTS = 1295


def _b36(value: int) -> str:
    return B36[value // 36] + B36[value % 36]


def _encode_payload(data: bytes) -> tuple[str, str]:
    compressor = zlib.compressobj(9, zlib.DEFLATED, -10)
    compressed = compressor.compress(data) + compressor.flush()
    encoding, raw = ("Z", compressed) if len(compressed) < len(data) else ("2", data)
    return encoding, base64.b32encode(raw).decode().rstrip("=")


def bbqr_split(data: bytes, file_type: str = "J", max_part_chars: int = 1000) -> list[str]:
    if len(file_type) != 1:
        raise ValueError(f"file_type must be one character, got {file_type!r}")
    max_data = (max_part_chars - HEADER_LEN) // 8 * 8
    if max_data < 8:
        raise ValueError(f"max_part_chars {max_part_chars} leaves no room for data")
    encoding, encoded = _encode_payload(data)
    total = max(1, (len(encoded) + max_data - 1) // max_data)
    if total > MAX_PARTS:
        raise ValueError(f"payload needs {total} parts, max is {MAX_PARTS}")
    per = (len(encoded) + total - 1) // total
    per = (per + 7) // 8 * 8
    return [
        f"B${encoding}{file_type}{_b36(total)}{_b36(index)}"
        + encoded[index * per : (index + 1) * per]
        for index in range(total)
    ]


def _parse_header(part: str) -> tuple[str, str, int, int, str]:
    if len(part) < HEADER_LEN or not part.startswith("B$"):
        raise ValueError(f"bad BBQr header: {part[:HEADER_LEN]!r}")
    try:
        total = B36.index(part[4]) * 36 + B36.index(part[5])
        index = B36.index(part[6]) * 36 + B36.index(part[7])
    except ValueError:
        raise ValueError(f"bad BBQr header: {part[:HEADER_LEN]!r}")
    if index >= total:
        raise ValueError(f"part index {index} out of range for total {total}")
    return part[2], part[3], total, index, part[HEADER_LEN:]


def bbqr_join(parts: Iterable[str]) -> tuple[str, bytes]:
    encoding = file_type = None
    total = None
    data_parts: dict[int, str] = {}
    for part in parts:
        enc, ftype, t, index, data = _parse_header(part)
        if encoding is None:
            encoding, file_type, total = enc, ftype, t
        elif (enc, ftype, t) != (encoding, file_type, total):
            raise ValueError("mixed BBQr series: encoding, type or total differ")
        if index in data_parts:
            if data_parts[index] != data:
                raise ValueError(f"conflicting data for part {index}")
            continue
        data_parts[index] = data
    if total is None:
        raise ValueError("no parts given")
    missing = [i for i in range(total) if i not in data_parts]
    if missing:
        raise ValueError(f"missing parts: {missing}")
    joined = "".join(data_parts[i] for i in range(total))
    if encoding == "H":
        raw = bytes.fromhex(joined)
    else:
        padding = "=" * (-len(joined) % 8)
        raw = base64.b32decode(joined + padding)
        if encoding == "Z":
            raw = zlib.decompress(raw, wbits=-10)
        elif encoding != "2":
            raise ValueError(f"unsupported BBQr encoding: {encoding!r}")
    return file_type, raw


def render_qr(text: str, kind: str = "svg", scale: int = 4, version: int | None = None) -> bytes:
    qr = segno.make(text, error="l", micro=False, version=version)
    buffer = io.BytesIO()
    qr.save(buffer, kind=kind, scale=scale)
    return buffer.getvalue()


def render_frames(parts: list[str], kind: str = "svg", scale: int = 4) -> list[bytes]:
    """Render every part at the version needed by the longest one."""
    if not parts:
        return []
    version = segno.make(max(parts, key=len), error="l", micro=False).version
    return [render_qr(part, kind=kind, scale=scale, version=version) for part in parts]
