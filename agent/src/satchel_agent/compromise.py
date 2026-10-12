"""DEMO: simulate a fully compromised agent to show loss stays bounded by the envelope."""

from decimal import Decimal

from satchel_core.events import emit
from satchel_core.regtest import RegtestNode, btc_to_sats
from satchel_core.transactions import DUST_LIMIT_SATS

PREFIX = "DEMO simulated compromise: "


def _emit(event_type: str, message: str, payload: dict) -> None:
    emit("agent", event_type, PREFIX + message, payload)


class LossSink:
    """The attacker's own wallet — a demo third party, never project keys."""

    def __init__(self, node: RegtestNode, name: str = "loss-sink"):
        self.node = node
        self.name = name
        self.last_address: str | None = None

    def ensure(self) -> None:
        self.node.ensure_wallet(self.name)

    def new_address(self) -> str:
        address = self.node.call(
            "getnewaddress", "loss-sink", "bech32", wallet=self.name
        )
        self.last_address = address
        return address

    def balance(self) -> dict:
        balances = self.node.call("getbalances", wallet=self.name)
        mine = balances.get("mine", {})
        return {
            "wallet": self.name,
            "confirmed_sats": btc_to_sats(
                Decimal(str(mine.get("trusted", 0)))
            ),
            "pending_sats": btc_to_sats(
                Decimal(str(mine.get("untrusted_pending", 0)))
            ),
        }

    def received_sats(self, address: str, minconf: int) -> int:
        amount = self.node.call(
            "getreceivedbyaddress", address, minconf, wallet=self.name
        )
        return btc_to_sats(Decimal(str(amount)))


def simulate_compromise(
    toolbox,
    laptop,
    sink: LossSink,
    *,
    request_sats: int = 5_000_000,
    purpose: str = "agent top-up",
    demo_auto: str | None = None,
) -> dict:
    _emit(
        "compromise_started",
        "attacker controls the agent process",
        {
            "session_id": toolbox.session_id,
            "agent_id": toolbox.agent_id,
        },
    )
    sink_address = sink.new_address()
    if not sink_address.startswith("bcrt1"):
        raise ValueError(
            f"sink address {sink_address!r} is not a regtest address"
        )

    wallet = toolbox.wallet
    drained_sats = 0
    drain_txid = None
    envelope_balance_before = 0
    pending_change = 0
    if wallet is not None:
        envelope_balance_before = wallet.balance_sats()
        pending_change = wallet.pending_change_sats()
        amount = wallet.max_payable_sats(sink_address)
        if amount >= DUST_LIMIT_SATS:
            drain_txid = wallet.pay(sink_address, amount)
            drained_sats = amount
            _emit(
                "compromise_envelope_drained",
                f"drained {amount} sats to the loss sink",
                {
                    "txid": drain_txid,
                    "amount_sats": amount,
                    "sink_address": sink_address,
                    "envelope_balance_before": envelope_balance_before,
                    "pending_change_sats": pending_change,
                },
            )
        else:
            _emit(
                "compromise_envelope_empty",
                "envelope cannot cover the dust limit plus fee",
                {
                    "reason": f"max payable {amount} below {DUST_LIMIT_SATS}",
                    "envelope_balance_before": envelope_balance_before,
                    "pending_change_sats": pending_change,
                },
            )
    else:
        _emit(
            "compromise_envelope_empty",
            "no envelope wallet in this session",
            {"reason": "no budget granted"},
        )

    _emit(
        "compromise_large_spend_requested",
        f"requesting {request_sats} sats from the main funds",
        {
            "sink_address": sink_address,
            "amount_sats": request_sats,
            "purpose": purpose,
        },
    )
    try:
        response = laptop.spend(
            sink_address, request_sats, purpose, demo_auto=demo_auto
        )
        large_spend = {
            "broadcast": bool(response.get("broadcast")),
            "txid": response.get("txid"),
            "stage": response.get("stage"),
            "reason": response.get("reason"),
        }
    except Exception as exc:
        large_spend = {
            "broadcast": False,
            "txid": None,
            "stage": "request",
            "reason": str(exc),
        }
    if large_spend["broadcast"]:
        _emit(
            "compromise_large_spend_approved",
            "the human approved the follow-up spend on the Ledger",
            {"txid": large_spend["txid"]},
        )
    else:
        _emit(
            "compromise_large_spend_blocked",
            "the follow-up spend was not broadcast",
            {
                "stage": large_spend["stage"],
                "reason": large_spend["reason"],
            },
        )

    report = {
        "sink_address": sink_address,
        "drained_sats": drained_sats,
        "drain_txid": drain_txid,
        "envelope_balance_before": envelope_balance_before,
        "large_spend": large_spend,
        "sink": sink.balance(),
    }
    _emit("compromise_finished", "simulation complete", report)
    return report
