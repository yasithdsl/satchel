"""Tests for PSBT building, signing, finalization and signature extraction."""

import base64
import math
import secrets

import pytest
from embit import ec
from embit.psbt import PSBT, DerivationPath
from embit.transaction import Transaction, TransactionOutput

from satchel_core.keys import MasterKey, NonHardenedPathError
from satchel_core.signing import SIGHASH_ALL, sign_digest, verify_digest
from satchel_core.transactions import (
    DUST_LIMIT_SATS,
    Output,
    SpendInput,
    build_psbt,
    estimate_vsize,
    extract_signatures,
    finalize_psbt,
    input_derivation,
    input_sighashes,
    sign_psbt,
)

SEED = bytes.fromhex("000102030405060708090a0b0c0d0e0f")
MASTER = MasterKey.from_seed(SEED)


def make_input(key, amount=100_000, vout=0, txid=None):
    return SpendInput(
        txid=txid or secrets.token_hex(32),
        vout=vout,
        amount_sats=amount,
        public_key=key.public_key,
    )


def make_output(amount=50_000):
    return Output(address=MASTER.receive(secrets.randbelow(1 << 30)).address, amount_sats=amount)


def sample_psbt(n_inputs=2):
    keys = [MASTER.envelope(i) for i in range(n_inputs)]
    inputs = [make_input(k, amount=100_000) for k in keys]
    outputs = [Output(MASTER.receive(1).address, 50_000)]
    change = Output(MASTER.change(0).address, 100_000 * n_inputs - 50_000 - 1_000)
    return build_psbt(inputs, outputs, change), keys


def test_fee_must_be_positive():
    key = MASTER.envelope(0)
    spend = make_input(key, amount=100_000)
    with pytest.raises(ValueError):
        build_psbt([spend], [Output(MASTER.receive(0).address, 100_000)])
    with pytest.raises(ValueError):
        build_psbt([spend], [Output(MASTER.receive(0).address, 100_001)])


@pytest.mark.parametrize(
    "address",
    [
        "bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4",
        "tb1qw508d6qejxtdg4y5r3zarvary0c5xw7kg3g4ty",
        "1BoatSLRHtKNngkdXEeobR76b53LETtpyT",
        "not-an-address",
    ],
)
def test_non_regtest_output_address_rejected(address):
    spend = make_input(MASTER.envelope(0))
    with pytest.raises(ValueError):
        build_psbt([spend], [Output(address, 50_000)])


def test_duplicate_input_rejected():
    key = MASTER.envelope(0)
    spend = make_input(key, txid="aa" * 32)
    with pytest.raises(ValueError):
        build_psbt([spend, spend], [make_output()])


@pytest.mark.parametrize(
    "public_key",
    ["ab" * 32, "04" + "ab" * 64, "05" + "ab" * 32, "zz" + "ab" * 32],
)
def test_bad_public_key_rejected(public_key):
    spend = SpendInput(
        txid="aa" * 32, vout=0, amount_sats=100_000, public_key=public_key
    )
    with pytest.raises(ValueError):
        build_psbt([spend], [make_output()])


@pytest.mark.parametrize("txid", ["ab", "zz" * 32, "aa" * 31, "aa" * 33, 123])
def test_bad_txid_rejected(txid):
    spend = SpendInput(
        txid=txid, vout=0, amount_sats=100_000, public_key=MASTER.envelope(0).public_key
    )
    with pytest.raises(ValueError):
        build_psbt([spend], [make_output()])


@pytest.mark.parametrize("vout", [-1, True, 1.5, "0"])
def test_bad_vout_rejected(vout):
    spend = SpendInput(
        txid="aa" * 32, vout=vout, amount_sats=100_000, public_key=MASTER.envelope(0).public_key
    )
    with pytest.raises(ValueError):
        build_psbt([spend], [make_output()])


@pytest.mark.parametrize("amount", [True, False, 0, -5, 1.5, "1000"])
def test_bad_amounts_rejected(amount):
    key = MASTER.envelope(0)
    spend = SpendInput(
        txid="aa" * 32, vout=0, amount_sats=amount, public_key=key.public_key
    )
    with pytest.raises(ValueError):
        build_psbt([spend], [make_output()])
    spend = make_input(key)
    with pytest.raises(ValueError):
        build_psbt([spend], [Output(MASTER.receive(0).address, amount)])


def test_no_inputs_or_outputs():
    key = MASTER.envelope(0)
    with pytest.raises(ValueError):
        build_psbt([], [make_output()])
    with pytest.raises(ValueError):
        build_psbt([make_input(key)], [])


def test_psbt_shape():
    spend = make_input(MASTER.envelope(0))
    outputs = [Output(MASTER.receive(0).address, 40_000), Output(MASTER.receive(1).address, 30_000)]
    change = Output(MASTER.change(0).address, 29_000)
    psbt = build_psbt([spend], outputs, change)
    assert psbt.tx.version == 2
    assert psbt.tx.locktime == 0
    assert all(vin.sequence == 0xFFFFFFFD for vin in psbt.tx.vin)
    assert len(psbt.tx.vout) == 3
    assert psbt.tx.vout[-1].value == 29_000
    assert psbt.inputs[0].witness_utxo.value == 100_000


def test_signing_is_deterministic():
    psbt, keys = sample_psbt()
    wifs = [k.wif for k in keys]
    assert sign_psbt(psbt, wifs).serialize() == sign_psbt(psbt, wifs).serialize()


def test_sign_psbt_key_matching():
    psbt, keys = sample_psbt()
    with pytest.raises(ValueError, match="input"):
        sign_psbt(psbt, [keys[0].wif])
    with pytest.raises(ValueError, match="no input"):
        sign_psbt(psbt, [k.wif for k in keys] + [MASTER.envelope(9).wif])


def test_sign_psbt_accepts_generator_wifs():
    psbt, keys = sample_psbt()
    signed = sign_psbt(psbt, (k.wif for k in keys))
    assert all(len(s.partial_sigs) == 1 for s in signed.inputs)
    with pytest.raises(ValueError, match="no input"):
        sign_psbt(
            psbt,
            (w for w in [keys[0].wif, keys[1].wif, MASTER.envelope(9).wif]),
        )


def test_extract_round_trip():
    psbt, keys = sample_psbt(n_inputs=3)
    sighashes = input_sighashes(psbt)
    signed = sign_psbt(psbt, [k.wif for k in keys])
    raw_tx = finalize_psbt(signed)
    extracted = extract_signatures(raw_tx, psbt)
    assert len(extracted) == 3
    for i, (entry, key) in enumerate(zip(extracted, keys)):
        assert entry.index == i
        assert entry.public_key == key.public_key
        assert entry.sighash_type == SIGHASH_ALL
        assert entry.sighash == sighashes[i]
        assert entry.signature == sign_digest(key.wif, sighashes[i])
        assert verify_digest(entry.public_key, entry.sighash, entry.signature)


def test_tampered_output_rejected():
    psbt, keys = sample_psbt()
    raw_tx = finalize_psbt(sign_psbt(psbt, [k.wif for k in keys]))
    tx = Transaction.parse(bytes.fromhex(raw_tx))
    tx.vout[0].value += 1
    with pytest.raises(ValueError, match="does not match"):
        extract_signatures(tx.serialize().hex(), psbt)


def test_swapped_witnesses_rejected():
    psbt, keys = sample_psbt(n_inputs=2)
    raw_tx = finalize_psbt(sign_psbt(psbt, [k.wif for k in keys]))
    tx = Transaction.parse(bytes.fromhex(raw_tx))
    tx.vin[0].witness, tx.vin[1].witness = tx.vin[1].witness, tx.vin[0].witness
    with pytest.raises(ValueError):
        extract_signatures(tx.serialize().hex(), psbt)


def test_estimate_vsize():
    addr = MASTER.receive(0).address  # p2wpkh: 22-byte scriptPubKey
    assert estimate_vsize(1, [addr]) == math.ceil(10.5 + 68 + 9 + 22)
    assert estimate_vsize(2, [addr, addr]) == math.ceil(10.5 + 136 + 62)
    assert DUST_LIMIT_SATS == 330


def test_extract_rejects_empty_witness_signature():
    psbt, keys = sample_psbt(n_inputs=2)
    raw_tx = finalize_psbt(sign_psbt(psbt, [k.wif for k in keys]))
    tx = Transaction.parse(bytes.fromhex(raw_tx))
    tx.vin[0].witness.items[0] = b""
    with pytest.raises(ValueError, match="too short"):
        extract_signatures(tx.serialize().hex(), psbt)


def test_finalize_requires_one_sig_per_input():
    psbt, _ = sample_psbt()
    with pytest.raises(ValueError):
        finalize_psbt(psbt)


@pytest.mark.regtest
def test_spend_end_to_end(node):
    master = MasterKey.from_seed(secrets.token_bytes(32))
    k1, k2 = master.receive(0), master.envelope(0)
    node.fund_address(k1.address, 200_000)
    node.fund_address(k2.address, 300_000)
    utxos = {u.address: u for u in node.list_unspent([k1.address, k2.address])}
    inputs = [
        SpendInput(utxos[k1.address].txid, utxos[k1.address].vout, 200_000, k1.public_key),
        SpendInput(utxos[k2.address].txid, utxos[k2.address].vout, 300_000, k2.public_key),
    ]
    destination = master.receive(7).address
    outputs = [Output(destination, 350_000)]
    change = Output(master.change(0).address, 149_000)
    psbt = build_psbt(inputs, outputs, change)
    signed = sign_psbt(psbt, [k1.wif, k2.wif])
    raw_tx = finalize_psbt(signed)
    accepted = node.call("testmempoolaccept", [raw_tx])[0]
    assert accepted["allowed"], accepted.get("reject-reason")
    expected_txid = node.call("decoderawtransaction", raw_tx)["txid"]
    assert node.broadcast(raw_tx) == expected_txid
    node.mine_blocks(1, node.faucet_address())
    dest_utxos = node.list_unspent([destination])
    assert len(dest_utxos) == 1
    assert dest_utxos[0].amount_sats == 350_000
    extracted = extract_signatures(raw_tx, psbt)
    sighashes = input_sighashes(psbt)
    for i, (entry, key) in enumerate(zip(extracted, [k1, k2])):
        assert entry.signature == sign_digest(key.wif, sighashes[i])
        assert entry.sighash == sighashes[i]
        assert entry.public_key == key.public_key


def make_derived_input(key, **kwargs):
    return SpendInput(
        txid=kwargs.pop("txid", secrets.token_hex(32)),
        vout=kwargs.pop("vout", 0),
        amount_sats=kwargs.pop("amount_sats", 100_000),
        public_key=key.public_key,
        path=key.path,
    )


def test_build_psbt_records_derivations():
    k0, k1 = MASTER.receive(0), MASTER.envelope(3)
    psbt = build_psbt(
        [make_derived_input(k0), make_derived_input(k1)],
        [make_output(50_000)],
        fingerprint=MASTER.fingerprint,
    )
    parsed = PSBT.parse(base64.b64decode(psbt.to_base64()))
    for i, key in enumerate((k0, k1)):
        pubkey, fingerprint, path = input_derivation(parsed, i)
        assert pubkey == key.public_key
        assert fingerprint == MASTER.fingerprint
        assert path == key.path


def test_build_psbt_mixed_paths():
    k0, k1 = MASTER.receive(0), MASTER.receive(1)
    psbt = build_psbt(
        [make_derived_input(k0), make_input(k1)],
        [make_output(50_000)],
        fingerprint=MASTER.fingerprint,
    )
    assert input_derivation(psbt, 0)[2] == k0.path
    assert input_derivation(psbt, 1) is None


def test_build_psbt_path_requires_fingerprint():
    spend = make_derived_input(MASTER.receive(0))
    for bad in (None, "xyz", "aabbcc", "aabbccdd00"):
        with pytest.raises(ValueError):
            build_psbt([spend], [make_output()], fingerprint=bad)


def test_build_psbt_rejects_non_hardened_path():
    key = MASTER.receive(0)
    spend = SpendInput(
        txid=secrets.token_hex(32),
        vout=0,
        amount_sats=100_000,
        public_key=key.public_key,
        path="m/84'/1'/0'/0/0'",
    )
    with pytest.raises(NonHardenedPathError):
        build_psbt([spend], [make_output()], fingerprint=MASTER.fingerprint)


def test_input_derivation_rejects_multiple():
    k0 = MASTER.receive(0)
    psbt = build_psbt(
        [make_derived_input(k0)],
        [make_output()],
        fingerprint=MASTER.fingerprint,
    )
    other = ec.PublicKey.parse(bytes.fromhex(MASTER.receive(1).public_key))
    psbt.inputs[0].bip32_derivations[other] = DerivationPath(
        bytes.fromhex(MASTER.fingerprint), []
    )
    with pytest.raises(ValueError):
        input_derivation(psbt, 0)
