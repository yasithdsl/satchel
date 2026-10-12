"""The single honest signing function: plain RFC6979 ECDSA over secp256k1."""

from embit import base58, ec

SIGHASH_ALL = 1
SECP256K1_N = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
WIF_PREFIX = 0xEF


def private_key_from_wif(wif: str) -> ec.PrivateKey:
    try:
        payload = base58.decode_check(wif)
    except ValueError as exc:
        raise ValueError(f"invalid WIF: {exc}") from exc
    if len(payload) != 34 or payload[0] != WIF_PREFIX or payload[33] != 0x01:
        raise ValueError("not a compressed regtest WIF")
    return ec.PrivateKey(payload[1:33])


def _der_int(der: bytes, offset: int) -> tuple[int, int]:
    if der[offset] != 0x02:
        raise ValueError("invalid DER signature: expected INTEGER")
    length = der[offset + 1]
    raw = der[offset + 2 : offset + 2 + length]
    if len(raw) != length or length == 0:
        raise ValueError("invalid DER signature: truncated INTEGER")
    if raw[0] & 0x80:
        raise ValueError("invalid DER signature: negative INTEGER")
    if length > 1 and raw[0] == 0 and not raw[1] & 0x80:
        raise ValueError("invalid DER signature: non-minimal INTEGER")
    return int.from_bytes(raw, "big"), offset + 2 + length


def der_to_rs(der: bytes) -> tuple[int, int]:
    if len(der) < 8 or der[0] != 0x30 or der[1] != len(der) - 2:
        raise ValueError("invalid DER signature")
    r, offset = _der_int(der, 2)
    s, offset = _der_int(der, offset)
    if offset != len(der):
        raise ValueError("invalid DER signature: trailing bytes")
    return r, s


def is_low_s(der: bytes) -> bool:
    return der_to_rs(der)[1] <= SECP256K1_N // 2


def sign_digest(wif: str, digest: bytes) -> bytes:
    """Sign a 32-byte digest with plain RFC6979 (DER, low-S, no sighash byte).

    Deliberately no extra entropy and no low-R grinding: the vault must be able
    to recompute every honest signature byte for byte, and any standard RFC6979
    implementation reproduces this output.
    """
    if len(digest) != 32:
        raise ValueError(f"digest must be 32 bytes, got {len(digest)}")
    key = private_key_from_wif(wif)
    der = key.sign(digest, grind=False).serialize()
    if not is_low_s(der):
        raise RuntimeError("signer produced a high-S signature")
    if not verify_digest(key.get_public_key().sec().hex(), digest, der):
        raise RuntimeError("signature failed self-verification")
    return der


def verify_digest(public_key_hex: str, digest: bytes, der: bytes) -> bool:
    try:
        public_key = ec.PublicKey.parse(bytes.fromhex(public_key_hex))
        return public_key.verify(ec.Signature.parse(der), digest)
    except (ValueError, TypeError, IndexError):
        return False
