"""Tests for hardened key derivation.

Address and public-key vectors below were produced with Bitcoin Core 30.2
(getdescriptorinfo / deriveaddresses on a wpkh(<tprv>/84h/1h/0h/<b>h/<i>h)
descriptor, and wpkh(<wif>) for the pubkeys), not with our code.
"""

import hashlib
import hmac
import secrets

import pytest
from embit import bip32, ec
from embit.networks import NETWORKS

from satchel_core.keys import (
    HARDENED,
    Branch,
    DerivedKey,
    MasterKey,
    NonHardenedPathError,
    parse_hardened_path,
)

SEED = bytes.fromhex("000102030405060708090a0b0c0d0e0f")
SECP256K1_N = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141

CORE_VECTORS = {
    (0, 0): (
        "02600bf496bf4b42b0a9600378ad9db69b362a631836370ec34ff8814845734dd6",
        "bcrt1qryk05z6rwgs4vc30laaf87xs6eznfvwul5mkca",
    ),
    (0, 1): (
        "03d2678241123b7b70f57530e4632f4256d737a474562e09ca9028bc16c7e836aa",
        "bcrt1qvwk9d3yj4t040jrlrnt26zs7k0s07kchjal4v0",
    ),
    (1, 0): (
        "02b818e4605560986e263576e41aa4a6e56517fb2b6339b6567c8d7a9fd573844c",
        "bcrt1q0vz3ck57rqq7wtv9vz5g8nxa66z3m66sgpprmv",
    ),
    (2, 0): (
        "0358dcb581bfcdd65bad08e60bff37a7c1bfc4489a80e09ce0ba20b21749fd294f",
        "bcrt1qgj835kmr4hrdvqn7r4ecnmch8n65870ytad338",
    ),
    (2, 1): (
        "0303632ba318f956cb4d794b58ce9e84a6f6f073d8cbb523b474119a02316b9286",
        "bcrt1q6u3wgu8sdzfjyzh8v9e2qa8lzwwrz5k52cctsj",
    ),
}


def test_root_matches_bip32_vector1():
    """MasterKey root equals the published BIP32 test-vector-1 master key."""
    vector = bip32.HDKey.from_string(
        "xprv9s21ZrQH143K3QTDL4LXw2F7HEK3wJUD2nW2nRk4stbPy6cq3jPPqjiChkVvvNKmPGJxWUtg6LnF5kejMRNNU3TGtRBeJgk33yuGBxrMPHi"
    )
    master = MasterKey.from_seed(SEED)
    assert master._root.chain_code == vector.chain_code
    assert master._root.key.secret == vector.key.secret


GETTERS = {0: MasterKey.receive, 1: MasterKey.change, 2: MasterKey.envelope}


@pytest.mark.parametrize("branch_index,index", sorted(CORE_VECTORS))
def test_derived_addresses_and_pubkeys_match_core(branch_index, index):
    """receive(0)/receive(1) etc. match Bitcoin Core 30.2 descriptor output."""
    public_key, address = CORE_VECTORS[(branch_index, index)]
    key = GETTERS[branch_index](MasterKey.from_seed(SEED), index)
    assert key.public_key == public_key
    assert key.address == address


@pytest.mark.parametrize("branch", [Branch.RECEIVE, Branch.CHANGE, Branch.ENVELOPE])
@pytest.mark.parametrize("index", [0, 1, 7, HARDENED - 1])
def test_every_level_hardened(branch, index):
    master = MasterKey.from_seed(SEED)
    key = master.derive(f"m/84'/1'/0'/{int(branch)}'/{index}'")
    components = bip32.parse_path(key.path)
    assert len(components) == 5
    assert all(c >= HARDENED for c in components)
    root = bip32.HDKey.from_seed(SEED, version=NETWORKS["regtest"]["xprv"])
    expected = root.derive([84 | HARDENED, 1 | HARDENED, 0 | HARDENED, int(branch) | HARDENED, index | HARDENED])
    assert key.public_key == expected.key.get_public_key().sec().hex()
    non_hardened_last = root.derive([84 | HARDENED, 1 | HARDENED, 0 | HARDENED, int(branch) | HARDENED, index])
    assert key.public_key != non_hardened_last.key.get_public_key().sec().hex()


def test_envelope_keys_unrelated():
    master = MasterKey.from_seed(SEED)
    e0, e1 = master.envelope(0), master.envelope(1)
    assert e0.wif != e1.wif
    assert e0.public_key != e1.public_key
    assert e0.address != e1.address
    root = bip32.HDKey.from_seed(SEED, version=NETWORKS["regtest"]["xprv"])
    branch_pub = root.derive([84 | HARDENED, 1 | HARDENED, 0 | HARDENED, 2 | HARDENED]).to_public()
    for index, key in ((0, e0), (1, e1)):
        public_child = branch_pub.derive([index]).key.sec().hex()
        assert public_child != key.public_key


@pytest.mark.parametrize(
    "path",
    ["m/84'/1'/0'/2'/5", "m/84'/1'/0'/2/5'", "m/84/1'/0'/0'/0'"],
)
def test_non_hardened_rejected(path):
    with pytest.raises(NonHardenedPathError):
        parse_hardened_path(path)


@pytest.mark.parametrize(
    "path",
    [
        "m/84'/0'/0'/0'/0'",
        "m/84'/1'/0'/3'/0'",
        "m/84'/1'/0'/0'",
        "m/44'/1'/0'/0'/0'",
        "m/84'/1'/0'/2'/+5'",
        "m/84'/1'/0'/2'/05'",
        "m/84'/1'/0'/2'/ 5'",
        "m/84'/1'/0'/2'/５'",
    ],
)
def test_wrong_template_rejected(path):
    with pytest.raises(ValueError) as exc:
        parse_hardened_path(path)
    assert not isinstance(exc.value, NonHardenedPathError)


@pytest.mark.parametrize("network", ["main", "test", "signet"])
def test_from_seed_rejects_non_regtest(network):
    with pytest.raises(ValueError):
        MasterKey.from_seed(SEED, network=network)


@pytest.mark.parametrize("index", [-1, HARDENED])
def test_bad_index_rejected(index):
    master = MasterKey.from_seed(SEED)
    with pytest.raises(ValueError):
        master.envelope(index)


def test_repr_hides_secrets():
    master = MasterKey.from_seed(SEED)
    key = master.envelope(0)
    tprv = bip32.HDKey.from_seed(SEED, version=NETWORKS["regtest"]["xprv"]).to_base58()
    assert key.wif not in repr(master)
    assert tprv not in repr(master)
    assert key.wif not in repr(key)


def recover_parent_private_key(parent_xpub: bip32.HDKey, child_secret: bytes, index: int) -> int:
    """The textbook non-hardened-derivation attack.

    For a non-hardened child, CKD uses I = HMAC-SHA512(parent chain code,
    parent_pubkey || ser32(index)) and child = parent + I_L, so anyone holding
    the parent xpub and one child private key recovers the parent private key.
    """
    data = parent_xpub.key.sec() + index.to_bytes(4, "big")
    i_l = int.from_bytes(hmac.new(parent_xpub.chain_code, data, hashlib.sha512).digest()[:32], "big")
    return (int.from_bytes(child_secret, "big") - i_l) % SECP256K1_N


def ckd_private(parent_secret: int, chain_code: bytes, index: int) -> int:
    if index & HARDENED:
        data = b"\x00" + parent_secret.to_bytes(32, "big") + index.to_bytes(4, "big")
    else:
        data = ec.PrivateKey(parent_secret.to_bytes(32, "big")).get_public_key().sec() + index.to_bytes(4, "big")
    i_l = int.from_bytes(hmac.new(chain_code, data, hashlib.sha512).digest()[:32], "big")
    return (parent_secret + i_l) % SECP256K1_N


def test_non_hardened_leak_exposes_whole_branch():
    root = bip32.HDKey.from_seed(SEED, version=NETWORKS["regtest"]["xprv"])
    parent = root.derive([84 | HARDENED, 1 | HARDENED, 0 | HARDENED, 0 | HARDENED])
    child = parent.derive([5])
    recovered = recover_parent_private_key(parent.to_public(), child.key.secret, 5)
    assert recovered == int.from_bytes(parent.key.secret, "big")
    sibling = ckd_private(recovered, parent.chain_code, 6)
    assert sibling == int.from_bytes(parent.derive([6]).key.secret, "big")


def test_hardened_envelope_key_survives_same_attack():
    master = MasterKey.from_seed(SEED)
    root = bip32.HDKey.from_seed(SEED, version=NETWORKS["regtest"]["xprv"])
    branch = root.derive([84 | HARDENED, 1 | HARDENED, 0 | HARDENED, 2 | HARDENED])
    leaked = master.envelope(5)
    recovered = recover_parent_private_key(
        branch.to_public(),
        ec.PrivateKey.from_string(leaked.wif).secret,
        5 | HARDENED,
    )
    assert recovered != int.from_bytes(branch.key.secret, "big")
    wrong_sibling = ckd_private(recovered, branch.chain_code, 6 | HARDENED)
    assert wrong_sibling != int.from_bytes(
        ec.PrivateKey.from_string(master.envelope(6).wif).secret, "big"
    )


@pytest.mark.regtest
def test_random_seed_addresses_match_core(node):
    """Cross-check against a live node: Core 30.2 deriveaddresses for a random seed."""
    seed = secrets.token_bytes(32)
    master = MasterKey.from_seed(seed)
    tprv = bip32.HDKey.from_seed(seed, version=NETWORKS["regtest"]["xprv"]).to_base58()
    for branch_index, index in [(0, 0), (1, 3), (2, 9)]:
        descriptor = f"wpkh({tprv}/84h/1h/0h/{branch_index}h/{index}h)"
        checksum = node.call("getdescriptorinfo", descriptor)["checksum"]
        key = master.derive(f"m/84'/1'/0'/{branch_index}'/{index}'")
        assert node.call("deriveaddresses", f"{descriptor}#{checksum}")[0] == key.address
        info = node.call("getdescriptorinfo", f"wpkh({key.wif})")["descriptor"]
        assert info.split("(")[1].split(")")[0] == key.public_key
