"""Prepaid-envelope wallet handed to the agent once a key is released."""

import math

from embit import script
from embit.transaction import Transaction

from satchel_core.events import emit
from satchel_core.keys import HARDENED, Branch, NETWORK, parse_hardened_path
from satchel_core.payloads import MessageType, Payload
from satchel_core.regtest import RPCError, RegtestNode, Utxo
from satchel_core.signing import private_key_from_wif
from satchel_core.transactions import (
    DUST_LIMIT_SATS,
    Output,
    SpendInput,
    build_psbt,
    estimate_vsize,
    finalize_psbt,
    sign_psbt,
)


class InsufficientFunds(ValueError):
    pass


class EnvelopeWallet:
    """Spends from one prepaid envelope key; deliberately no spending policy —
    the only limit is what's in the envelope."""

    def __init__(
        self,
        node: RegtestNode,
        envelope_index: int,
        address: str,
        public_key: str,
        budget_sats: int,
        agent_id: str,
        fee_rate_sat_vb: float,
        wif: str,
    ):
        self.node = node
        self.envelope_index = envelope_index
        self.address = address
        self.public_key = public_key
        self.budget_sats = budget_sats
        self.agent_id = agent_id
        self.fee_rate_sat_vb = fee_rate_sat_vb
        self._wif = wif

    @classmethod
    def from_key_release(
        cls,
        payload: Payload,
        node: RegtestNode,
        fee_rate_sat_vb: float = 2,
    ) -> "EnvelopeWallet":
        if payload.type != MessageType.KEY_RELEASE:
            raise ValueError(f"expected key_release, got {payload.type}")
        body = payload.body
        for name, kind in (
            ("envelope_index", int),
            ("path", str),
            ("address", str),
            ("public_key", str),
            ("wif", str),
            ("budget_sats", int),
            ("agent_id", str),
        ):
            value = body.get(name)
            if not isinstance(value, kind) or (
                kind is int and isinstance(value, bool)
            ):
                raise ValueError(
                    f"key_release body {name!r} must be a {kind.__name__}"
                )

        indexes = parse_hardened_path(body["path"])
        if indexes[3] != Branch.ENVELOPE | HARDENED:
            raise ValueError(f"path {body['path']} is not an envelope key")
        if indexes[4] & ~HARDENED != body["envelope_index"]:
            raise ValueError(
                f"path index {indexes[4] & ~HARDENED} != envelope_index "
                f"{body['envelope_index']}"
            )
        key = private_key_from_wif(body["wif"])
        if key.get_public_key().sec().hex() != body["public_key"]:
            raise ValueError("WIF public key does not match public_key")
        if (
            script.p2wpkh(key.get_public_key()).address(NETWORK)
            != body["address"]
        ):
            raise ValueError("address does not match public_key")

        wallet = cls(
            node,
            body["envelope_index"],
            body["address"],
            body["public_key"],
            body["budget_sats"],
            body["agent_id"],
            fee_rate_sat_vb,
            body["wif"],
        )
        emit(
            "agent",
            "wallet_loaded",
            f"envelope {wallet.envelope_index} loaded for {wallet.agent_id}",
            {
                "envelope_index": wallet.envelope_index,
                "address": wallet.address,
                "budget_sats": wallet.budget_sats,
                "agent_id": wallet.agent_id,
            },
        )
        return wallet

    def __repr__(self) -> str:
        return (
            f"EnvelopeWallet(envelope_index={self.envelope_index}, "
            f"address={self.address!r}, budget_sats={self.budget_sats}, "
            f"agent_id={self.agent_id!r})"
        )

    def spendable_utxos(self) -> list[Utxo]:
        return [
            u
            for u in self.node.list_unspent([self.address])
            if self.node.is_unspent(u.txid, u.vout, include_mempool=True)
        ]

    def balance_sats(self) -> int:
        return sum(u.amount_sats for u in self.spendable_utxos())

    def max_payable_sats(self, address: str) -> int:
        utxos = self.spendable_utxos()
        total = sum(u.amount_sats for u in utxos)
        return max(0, total - self._fee(len(utxos), [address]))

    def _fee(self, n_inputs: int, outputs: list[str]) -> int:
        return math.ceil(
            estimate_vsize(n_inputs, outputs) * self.fee_rate_sat_vb
        )

    def pay(self, address: str, amount_sats: int) -> str:
        try:
            if not isinstance(address, str) or not address.startswith("bcrt1"):
                raise ValueError(f"not a regtest address: {address!r}")
            if (
                isinstance(amount_sats, bool)
                or not isinstance(amount_sats, int)
                or amount_sats < DUST_LIMIT_SATS
            ):
                raise ValueError(
                    f"amount_sats must be an integer >= {DUST_LIMIT_SATS}"
                )

            utxos = self.spendable_utxos()
            total = sum(u.amount_sats for u in utxos)

            fee_with_change = self._fee(len(utxos), [address, self.address])
            change = None
            if total >= amount_sats + fee_with_change + DUST_LIMIT_SATS:
                change_sats = total - amount_sats - fee_with_change
                # Change goes back to the envelope's own address; address reuse is a demo simplification.
                change = Output(self.address, change_sats)
                fee_sats = fee_with_change
            else:
                fee_no_change = self._fee(len(utxos), [address])
                if total < amount_sats + fee_no_change:
                    raise InsufficientFunds(
                        f"need {amount_sats + fee_no_change}, have {total}"
                    )
                change_sats = 0
                fee_sats = total - amount_sats

            psbt = build_psbt(
                [
                    SpendInput(u.txid, u.vout, u.amount_sats, self.public_key)
                    for u in utxos
                ],
                [Output(address, amount_sats)],
                change,
            )
            raw = finalize_psbt(sign_psbt(psbt, [self._wif]))
        except ValueError as exc:
            emit(
                "agent",
                "payment_rejected",
                str(exc),
                {
                    "envelope_index": self.envelope_index,
                    "to": address,
                    "amount_sats": amount_sats
                    if isinstance(amount_sats, int)
                    else None,
                    "reason": str(exc),
                },
            )
            raise

        expected = Transaction.parse(bytes.fromhex(raw)).txid().hex()
        try:
            txid = self.node.broadcast(raw)
        except RPCError:
            emit(
                "agent",
                "payment_failed",
                f"broadcast of {expected} failed",
                {"envelope_index": self.envelope_index, "txid": expected},
            )
            raise
        if txid != expected:
            raise RuntimeError(f"broadcast txid {txid} != built txid {expected}")
        emit(
            "agent",
            "payment_sent",
            f"{amount_sats} sats to {address} in {txid}",
            {
                "envelope_index": self.envelope_index,
                "txid": txid,
                "to": address,
                "amount_sats": amount_sats,
                "fee_sats": fee_sats,
                "change_sats": change_sats,
            },
        )
        return txid
