"""Build Bitcoin Core-style txout proofs (CMerkleBlock) for tests.

Independent of the vault's parser: follows CPartialMerkleTree's
TraverseAndBuild, and grinds a header nonce to meet regtest's easy target.
"""

import hashlib

REGTEST_BITS = 0x207FFFFF


def sha256d(data: bytes) -> bytes:
    return hashlib.sha256(hashlib.sha256(data).digest()).digest()


def _compact_size(n: int) -> bytes:
    if n < 0xFD:
        return bytes([n])
    if n <= 0xFFFF:
        return b"\xfd" + n.to_bytes(2, "little")
    return b"\xfe" + n.to_bytes(4, "little")


def _target(bits: int) -> int:
    return (bits & 0x007FFFFF) << (8 * ((bits >> 24) - 3))


def header_for(merkle_root: bytes, bits: int = REGTEST_BITS) -> bytes:
    """An 80-byte header committing to merkle_root that meets its target."""
    for nonce in range(1 << 20):
        header = (
            (0x20000000).to_bytes(4, "little")
            + bytes(32)
            + merkle_root
            + (1_760_000_000).to_bytes(4, "little")
            + bits.to_bytes(4, "little")
            + nonce.to_bytes(4, "little")
        )
        if int.from_bytes(sha256d(header), "little") <= _target(bits):
            return header
    raise RuntimeError("could not meet the target")


def build_proof(txids: list[str], match: int, header: bytes | None = None) -> str:
    """A txout proof for txids[match] in a block holding exactly `txids`."""
    leaves = [bytes.fromhex(t)[::-1] for t in txids]
    total = len(leaves)

    def width(height: int) -> int:
        return (total + (1 << height) - 1) >> height

    def calc(height: int, pos: int) -> bytes:
        if height == 0:
            return leaves[pos]
        left = calc(height - 1, pos * 2)
        right = (
            calc(height - 1, pos * 2 + 1)
            if pos * 2 + 1 < width(height - 1)
            else left
        )
        return sha256d(left + right)

    flags: list[int] = []
    hashes: list[bytes] = []

    def build(height: int, pos: int) -> None:
        first = pos << height
        last = min((pos + 1) << height, total)
        parent_of_match = int(first <= match < last)
        flags.append(parent_of_match)
        if height == 0 or not parent_of_match:
            hashes.append(calc(height, pos))
            return
        build(height - 1, pos * 2)
        if pos * 2 + 1 < width(height - 1):
            build(height - 1, pos * 2 + 1)

    height = 0
    while width(height) > 1:
        height += 1
    build(height, 0)
    if header is None:
        header = header_for(calc(height, 0))
    flag_bytes = bytearray((len(flags) + 7) // 8)
    for i, bit in enumerate(flags):
        flag_bytes[i // 8] |= bit << (i % 8)
    return (
        header
        + total.to_bytes(4, "little")
        + _compact_size(len(hashes))
        + b"".join(hashes)
        + _compact_size(len(flag_bytes))
        + bytes(flag_bytes)
    ).hex()
