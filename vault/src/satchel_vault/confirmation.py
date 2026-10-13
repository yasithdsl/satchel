"""Offline check that a transaction is confirmed: a Bitcoin Core txout proof.

The vault never touches the network, so the laptop hands it the output of
`gettxoutproof` (a block header plus a partial merkle tree). The vault checks
the header's proof of work and that the tree commits the exact transaction id
to the header's merkle root. On regtest the work is trivial; on mainnet the
same proof would carry real work. Follows Bitcoin Core's CPartialMerkleTree.
"""

import hashlib
import re

HEADER_SIZE = 80
# MAX_BLOCK_WEIGHT / MIN_TRANSACTION_WEIGHT in Bitcoin Core.
MAX_TRANSACTIONS = 4_000_000 // 240
# Loosest target any network allows (regtest's powLimit is just below 2^255).
MAX_TARGET = 2**255
MAX_PROOF_BYTES = HEADER_SIZE + 4 + 9 + 32 * MAX_TRANSACTIONS + 9 + MAX_TRANSACTIONS
TXID_RE = re.compile(r"^[0-9a-f]{64}$")


class InvalidProof(ValueError):
    """The txout proof is malformed or does not prove the transaction."""


def _sha256d(data: bytes) -> bytes:
    return hashlib.sha256(hashlib.sha256(data).digest()).digest()


class _Reader:
    def __init__(self, data: bytes):
        self.data = data
        self.pos = 0

    def take(self, n: int) -> bytes:
        if n < 0 or self.pos + n > len(self.data):
            raise InvalidProof("proof is truncated")
        chunk = self.data[self.pos : self.pos + n]
        self.pos += n
        return chunk

    def u32(self) -> int:
        return int.from_bytes(self.take(4), "little")

    def compact_size(self) -> int:
        first = self.take(1)[0]
        if first < 0xFD:
            return first
        width = {0xFD: 2, 0xFE: 4, 0xFF: 8}[first]
        return int.from_bytes(self.take(width), "little")


def target_from_bits(bits: int) -> int:
    exponent = bits >> 24
    mantissa = bits & 0x007FFFFF
    if bits & 0x00800000:
        raise InvalidProof("negative difficulty target")
    if exponent <= 3:
        return mantissa >> (8 * (3 - exponent))
    return mantissa << (8 * (exponent - 3))


def verify_txout_proof(proof_hex: str, txid: str) -> dict:
    """Check that `proof_hex` proves `txid` is in a block with valid work.

    Returns {"block_hash": ...}; raises InvalidProof otherwise.
    """
    if not isinstance(txid, str) or not TXID_RE.fullmatch(txid):
        raise InvalidProof("txid must be 64 lowercase hex chars")
    if not isinstance(proof_hex, str) or len(proof_hex) > 2 * MAX_PROOF_BYTES:
        raise InvalidProof("proof must be a hex string of sane size")
    try:
        raw = bytes.fromhex(proof_hex)
    except ValueError as exc:
        raise InvalidProof("proof is not hex") from exc

    reader = _Reader(raw)
    header = reader.take(HEADER_SIZE)
    merkle_root = header[36:68]
    bits = int.from_bytes(header[72:76], "little")
    target = target_from_bits(bits)
    if target <= 0 or target > MAX_TARGET:
        raise InvalidProof("difficulty target out of range")
    block_hash = _sha256d(header)
    if int.from_bytes(block_hash, "little") > target:
        raise InvalidProof("block header does not meet its proof of work")

    total = reader.u32()
    if total == 0 or total > MAX_TRANSACTIONS:
        raise InvalidProof("implausible transaction count")
    hash_count = reader.compact_size()
    if hash_count > total:
        raise InvalidProof("more hashes than transactions")
    hashes = [reader.take(32) for _ in range(hash_count)]
    flag_bytes = reader.take(reader.compact_size())
    if reader.pos != len(raw):
        raise InvalidProof("trailing bytes after the proof")
    flags = [(flag_bytes[i // 8] >> (i % 8)) & 1 for i in range(len(flag_bytes) * 8)]
    if len(flags) < hash_count:
        raise InvalidProof("fewer flag bits than hashes")

    def width(height: int) -> int:
        return (total + (1 << height) - 1) >> height

    used = {"bits": 0, "hashes": 0}
    matches: list[bytes] = []

    def traverse(height: int, pos: int) -> bytes:
        if used["bits"] >= len(flags):
            raise InvalidProof("ran out of flag bits")
        parent_of_match = flags[used["bits"]]
        used["bits"] += 1
        if height == 0 or not parent_of_match:
            if used["hashes"] >= len(hashes):
                raise InvalidProof("ran out of hashes")
            node = hashes[used["hashes"]]
            used["hashes"] += 1
            if height == 0 and parent_of_match:
                matches.append(node)
            return node
        left = traverse(height - 1, pos * 2)
        if pos * 2 + 1 < width(height - 1):
            right = traverse(height - 1, pos * 2 + 1)
            if right == left:
                # Duplicate subtrees let one tree prove two different blocks.
                raise InvalidProof("duplicate merkle branch")
        else:
            right = left
        return _sha256d(left + right)

    height = 0
    while width(height) > 1:
        height += 1
    root = traverse(height, 0)
    if (used["bits"] + 7) // 8 != len(flag_bytes):
        raise InvalidProof("unused flag bytes")
    if used["hashes"] != len(hashes):
        raise InvalidProof("unused hashes")
    if root != merkle_root:
        raise InvalidProof("merkle root does not match the block header")
    if bytes.fromhex(txid)[::-1] not in matches:
        raise InvalidProof("the proof does not include this transaction")
    return {"block_hash": block_hash[::-1].hex()}
