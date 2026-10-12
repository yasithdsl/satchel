"""Large-spend flow and broadcast gating against stubs."""

import ast
import base64
import hashlib
import json
from pathlib import Path

import pytest
from embit.psbt import PSBT
from embit.transaction import Transaction

from satchel_core.keys import MasterKey
from satchel_core.payloads import MessageType, Payload
from satchel_core.regtest import Utxo
from satchel_core.transactions import (
    finalize_psbt,
    sign_psbt,
    wtxid,
)
from satchel_laptop.approver_client import ApprovalOutcome, ApproverError
from satchel_laptop.signer_client import SignerError
from satchel_laptop.broadcast import NotVerified, broadcast_verified
from satchel_laptop.spend import large_spend
from satchel_laptop.state import LaptopState
from satchel_laptop.vault_client import VaultRefused

SEED = bytes.fromhex("000102030405060708090a0b0c0d0e0f")
MASTER = MasterKey.from_seed(SEED)
DEST = MasterKey.from_seed(b"\x99" * 16).receive(0).address


def change_entry(index=0):
    key = MASTER.change(index)
    return {
        "kind": "change",
        "index": index,
        "path": key.path,
        "address": key.address,
        "public_key": key.public_key,
    }


def change_payload(entry=None):
    entry = entry or change_entry()
    return Payload(
        MessageType.ADDRESS_EXPORT,
        {
            "kind": "change",
            "fingerprint": MASTER.fingerprint,
            "addresses": [entry],
        },
    )


def utxo(address, amount, seed_byte):
    return Utxo(
        txid=hashlib.sha256(bytes([seed_byte])).hexdigest(),
        vout=0,
        address=address,
        amount_sats=amount,
        script_pubkey="0014" + "ab" * 20,
        height=100,
        coinbase=False,
    )


class StubNode:
    def __init__(self, utxos=()):
        self.utxos = {(u.txid, u.vout): u for u in utxos}
        self.broadcast_calls = []

    def list_unspent(self, addresses):
        wanted = set(addresses)
        return [u for u in self.utxos.values() if u.address in wanted]

    def is_unspent(self, txid, vout, include_mempool=True):
        return (txid, vout) in self.utxos

    def broadcast(self, raw_hex):
        self.broadcast_calls.append(raw_hex)
        return Transaction.parse(bytes.fromhex(raw_hex)).txid().hex()


class HonestSigner:
    def __init__(self):
        self.calls = []

    def request_signature(self, psbt_payload, key_release):
        self.calls.append(key_release)
        wifs = [k["wif"] for k in key_release.body["keys"]]
        psbt = PSBT.parse(base64.b64decode(psbt_payload.body["psbt"]))
        raw = finalize_psbt(sign_psbt(psbt, wifs))
        return Payload(
            MessageType.SIGNED_TX, {"tx": raw, "txid": psbt.tx.txid().hex()}
        )


class StubVault:
    def __init__(self, change, refuse=None, fail_verify=False):
        self.change = change
        self.refuse = refuse
        self.fail_verify = fail_verify
        self.release_calls = []
        self.verify_calls = []

    def export_change(self, count):
        return change_payload(self.change)

    def release_spend(self, approval, psbt_payload):
        self.release_calls.append(psbt_payload)
        if self.refuse is not None:
            raise self.refuse
        psbt = PSBT.parse(base64.b64decode(psbt_payload.body["psbt"]))
        keys = []
        for i in range(len(psbt.inputs)):
            deriv = next(iter(psbt.inputs[i].bip32_derivations.values()))
            path = "m/" + "/".join(
                f"{idx & 0x7FFFFFFF}'" for idx in deriv.derivation
            )
            keys.append({"path": path, "wif": MASTER.derive(path).wif})
        return Payload(
            MessageType.KEY_RELEASE, {"kind": "signing", "keys": keys}
        )

    def verify(self, psbt_payload, signed_payload):
        self.verify_calls.append(signed_payload)
        tx_hex = signed_payload.body["tx"]
        body = {
            "result": "fail" if self.fail_verify else "pass",
            "txid": Transaction.parse(bytes.fromhex(tx_hex)).txid().hex(),
            "wtxid": wtxid(tx_hex),
            "inputs": 1,
            "failures": (
                [
                    {
                        "scope": "input",
                        "index": 0,
                        "reason": "input 0 signature is not the deterministic signature",
                    }
                ]
                if self.fail_verify
                else []
            ),
        }
        return Payload(MessageType.VERIFICATION_RESULT, body)


def funded_state(tmp_path, amounts=(50_000,)):
    state = LaptopState(tmp_path / "state.json")
    entries = []
    for i, _ in enumerate(amounts):
        key = MASTER.receive(i)
        entries.append(
            {
                "kind": "receive",
                "index": i,
                "path": key.path,
                "address": key.address,
                "public_key": key.public_key,
            }
        )
    state.add_main_funds(MASTER.fingerprint, entries)
    node = StubNode(
        [utxo(MASTER.receive(i).address, amount, i + 1)
         for i, amount in enumerate(amounts)]
    )
    return state, node


def approval():
    return ApprovalOutcome(
        True, Payload(MessageType.LEDGER_APPROVAL, {}), None, None, None
    )


class OneApprover:
    def __init__(self, outcome=None):
        self.outcome = outcome or approval()
        self.calls = []

    def approve(self, plan, demo_auto=None):
        self.calls.append(plan)
        return self.outcome


def test_broadcast_success(tmp_path):
    state, node = funded_state(tmp_path, (50_000,))
    vault = StubVault(change_entry())
    result = large_spend(
        DEST,
        10_000,
        "test",
        vault=vault,
        approver=OneApprover(),
        signer=HonestSigner(),
        node=node,
        state=state,
        flows_dir=tmp_path / "flows",
    )
    assert result.broadcast and result.stage == "broadcast" and result.txid
    assert len(node.broadcast_calls) == 1
    flow = json.loads(
        (tmp_path / "flows" / "flows" / f"{result.flow_id}.json").read_text()
    )
    assert [h["name"] for h in flow["hops"]] == [
        "change_address_exported",
        "utxos_selected",
        "psbt_built",
        "plan_sent_to_approver",
        "approval_received",
        "approval_sent_to_vault",
        "keys_released",
        "keys_sent_to_signer",
        "signed_tx_received",
        "verification_received",
        "broadcast",
    ]
    wif = MASTER.receive(0).wif
    assert wif not in (tmp_path / "flows" / "flows" / f"{result.flow_id}.json").read_text()


def test_largest_first_and_multi_input(tmp_path):
    state, node = funded_state(tmp_path, (10_000, 90_000, 40_000))
    vault = StubVault(change_entry())
    large_spend(
        DEST,
        80_000,
        "test",
        vault=vault,
        approver=OneApprover(),
        signer=HonestSigner(),
        node=node,
        state=state,
        flows_dir=tmp_path / "flows",
    )
    psbt = PSBT.parse(
        base64.b64decode(vault.release_calls[0].body["psbt"])
    )
    spent = {(i.txid.hex(), i.vout) for i in psbt.tx.vin}
    big = utxo(MASTER.receive(1).address, 90_000, 2)
    assert spent == {(big.txid, big.vout)}

    state2, node2 = funded_state(tmp_path / "two", (10_000, 30_000, 40_000))
    vault2 = StubVault(change_entry())
    large_spend(
        DEST,
        60_000,
        "test",
        vault=vault2,
        approver=OneApprover(),
        signer=HonestSigner(),
        node=node2,
        state=state2,
        flows_dir=tmp_path / "f2",
    )
    psbt2 = PSBT.parse(
        base64.b64decode(vault2.release_calls[0].body["psbt"])
    )
    assert len(psbt2.tx.vin) == 2


def test_insufficient_funds_skips_approver(tmp_path):
    state, node = funded_state(tmp_path, (10_000,))
    approver = OneApprover()
    result = large_spend(
        DEST,
        1_000_000,
        "test",
        vault=StubVault(change_entry()),
        approver=approver,
        signer=HonestSigner(),
        node=node,
        state=state,
        flows_dir=tmp_path / "flows",
    )
    assert result.stage == "select" and not result.broadcast
    assert "insufficient" in result.reason
    assert approver.calls == []


def test_dust_change_dropped(tmp_path):
    # Choose an amount so the change would be under 330 sats.
    state, node = funded_state(tmp_path, (50_000,))
    vault = StubVault(change_entry())
    # fee with change ~= vsize(1 in, 2 out) * 2; pick amount to leave ~200 change
    result = large_spend(
        DEST,
        49_500,
        "test",
        vault=vault,
        approver=OneApprover(),
        signer=HonestSigner(),
        node=node,
        state=state,
        flows_dir=tmp_path / "flows",
    )
    assert result.broadcast
    psbt = PSBT.parse(
        base64.b64decode(vault.release_calls[0].body["psbt"])
    )
    assert len(psbt.tx.vout) == 1  # remainder went to the fee


def test_approval_rejected_stops_before_release(tmp_path):
    state, node = funded_state(tmp_path, (50_000,))
    vault = StubVault(change_entry())
    approver = OneApprover(
        ApprovalOutcome(False, None, "Rejected on the Ledger", "ab" * 8, "t")
    )
    result = large_spend(
        DEST,
        10_000,
        "test",
        vault=vault,
        approver=approver,
        signer=HonestSigner(),
        node=node,
        state=state,
        flows_dir=tmp_path / "flows",
    )
    assert result.stage == "approval" and not result.broadcast
    assert vault.release_calls == []


def test_release_refused_skips_signer(tmp_path):
    state, node = funded_state(tmp_path, (50_000,))
    vault = StubVault(change_entry(), refuse=VaultRefused(403, "bad plan"))
    signer = HonestSigner()
    result = large_spend(
        DEST,
        10_000,
        "test",
        vault=vault,
        approver=OneApprover(),
        signer=signer,
        node=node,
        state=state,
        flows_dir=tmp_path / "flows",
    )
    assert result.stage == "release" and result.reason == "bad plan"
    assert signer.calls == []


def test_verification_fail_never_broadcasts(tmp_path):
    state, node = funded_state(tmp_path, (50_000,))
    vault = StubVault(change_entry(), fail_verify=True)
    result = large_spend(
        DEST,
        10_000,
        "test",
        vault=vault,
        approver=OneApprover(),
        signer=HonestSigner(),
        node=node,
        state=state,
        flows_dir=tmp_path / "flows",
    )
    assert result.stage == "verification" and not result.broadcast
    assert "deterministic" in result.reason
    assert node.broadcast_calls == []


def signed_fixture():
    key = MASTER.receive(0)
    import satchel_core.transactions as tx_mod

    built = tx_mod.build_psbt(
        [
            tx_mod.SpendInput(
                "aa" * 32, 0, 50_000, key.public_key, key.path
            )
        ],
        [tx_mod.Output(DEST, 40_000)],
        tx_mod.Output(
            MASTER.change(0).address,
            9_000,
            MASTER.change(0).path,
            MASTER.change(0).public_key,
        ),
        fingerprint=MASTER.fingerprint,
    )
    raw = finalize_psbt(sign_psbt(built, [key.wif]))
    return raw


def verification_for(raw_hex, result="pass", failures=(), txid=None, wx=None):
    parsed = Transaction.parse(bytes.fromhex(raw_hex))
    return Payload(
        MessageType.VERIFICATION_RESULT,
        {
            "result": result,
            "txid": txid if txid is not None else parsed.txid().hex(),
            "wtxid": wx if wx is not None else wtxid(raw_hex),
            "inputs": 1,
            "failures": list(failures),
        },
    )


def signed_payload(raw_hex):
    txid = Transaction.parse(bytes.fromhex(raw_hex)).txid().hex()
    return Payload(MessageType.SIGNED_TX, {"tx": raw_hex, "txid": txid})


def test_broadcast_verified_refusals():
    raw = signed_fixture()
    node = StubNode()
    signed = signed_payload(raw)
    with pytest.raises(NotVerified):
        broadcast_verified(node, signed, verification_for(raw, result="fail"))
    with pytest.raises(NotVerified):
        broadcast_verified(
            node,
            signed,
            verification_for(
                raw,
                failures=[{"scope": "i", "index": 0, "reason": "x"}],
            ),
        )
    with pytest.raises(NotVerified):
        broadcast_verified(node, signed, Payload(MessageType.SIGNED_TX, {}))
    with pytest.raises(NotVerified):
        broadcast_verified(
            node, Payload(MessageType.UNSIGNED_PSBT, {}), verification_for(raw)
        )
    with pytest.raises(NotVerified):
        broadcast_verified(node, signed, verification_for(raw, txid="00" * 32))
    assert node.broadcast_calls == []


def test_broadcast_verified_wtxid_mismatch():
    # Re-sign the same PSBT with a random nonce: same txid, different wtxid.
    from satchel_signer.random_nonce import resign_with_random_nonces

    key = MASTER.receive(0)
    import satchel_core.transactions as tx_mod

    built = tx_mod.build_psbt(
        [tx_mod.SpendInput("aa" * 32, 0, 50_000, key.public_key, key.path)],
        [tx_mod.Output(DEST, 40_000)],
        tx_mod.Output(
            MASTER.change(0).address,
            9_000,
            MASTER.change(0).path,
            MASTER.change(0).public_key,
        ),
        fingerprint=MASTER.fingerprint,
    )
    honest = finalize_psbt(sign_psbt(built, [key.wif]))
    rogue = finalize_psbt(
        resign_with_random_nonces(sign_psbt(built, [key.wif]), [key.wif])
    )
    verification = verification_for(honest)
    node = StubNode()
    with pytest.raises(NotVerified, match="wtxid"):
        broadcast_verified(node, signed_payload(rogue), verification)
    assert node.broadcast_calls == []


def test_broadcast_verified_success():
    raw = signed_fixture()
    node = StubNode()
    txid = broadcast_verified(node, signed_payload(raw), verification_for(raw))
    assert txid == Transaction.parse(bytes.fromhex(raw)).txid().hex()
    assert node.broadcast_calls == [raw]


def test_only_broadcast_module_may_broadcast():
    root = Path(__file__).resolve().parents[1] / "src" / "satchel_laptop"
    offenders = []
    for path in root.rglob("*.py"):
        if path.name == "broadcast.py":
            continue
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "broadcast"
            ):
                offenders.append(f"{path.name}:{node.lineno}")
    assert offenders == []


def _flow_files(directory: Path) -> list[Path]:
    return sorted(directory.glob("*.json"))


def test_approver_error_fails_flow(tmp_path):
    class DownApprover:
        def approve(self, plan, demo_auto=None):
            raise ApproverError("approver unreachable")

    state, node = funded_state(tmp_path, (50_000,))
    with pytest.raises(ApproverError):
        large_spend(
            DEST,
            10_000,
            "test",
            vault=StubVault(change_entry()),
            approver=DownApprover(),
            signer=HonestSigner(),
            node=node,
            state=state,
            flows_dir=tmp_path / "flows",
        )
    flows = _flow_files(tmp_path / "flows" / "flows")
    assert len(flows) == 1
    doc = json.loads(flows[0].read_text())
    assert doc["status"] == "failed"
    assert doc["result"]["stage"] == "approval"
    assert "approver unreachable" in doc["result"]["error"]
    import os

    events = Path(os.environ["SATCHEL_EVENT_LOG"]).read_text()
    assert '"spend_failed"' in events


def test_signer_error_fails_flow(tmp_path):
    class DeadSigner:
        def request_signature(self, psbt_payload, key_release):
            raise SignerError("signer refused")

    state, node = funded_state(tmp_path, (50_000,))
    with pytest.raises(SignerError):
        large_spend(
            DEST,
            10_000,
            "test",
            vault=StubVault(change_entry()),
            approver=OneApprover(),
            signer=DeadSigner(),
            node=node,
            state=state,
            flows_dir=tmp_path / "flows",
        )
    flows = _flow_files(tmp_path / "flows" / "flows")
    assert len(flows) == 1
    doc = json.loads(flows[0].read_text())
    assert doc["status"] == "failed"
    assert doc["result"]["stage"] == "sign"
    assert "signer refused" in doc["result"]["error"]


def test_validation_rejected(tmp_path):
    state, node = funded_state(tmp_path, (50_000,))
    kwargs = dict(
        vault=StubVault(change_entry()),
        approver=OneApprover(),
        signer=HonestSigner(),
        node=node,
        state=state,
        flows_dir=tmp_path / "f",
    )
    with pytest.raises(ValueError):
        large_spend("bc1qmainnet", 10_000, "ok", **kwargs)
    with pytest.raises(ValueError):
        large_spend(DEST, 100, "ok", **kwargs)
    with pytest.raises(ValueError):
        large_spend(DEST, 10_000, "bad\npurpose", **kwargs)
