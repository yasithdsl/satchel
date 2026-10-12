"""Event enrichment: diagram nodes, labels, QR parts, alerts, simulation."""

import json
import re
from pathlib import Path

NODES = {
    "agent",
    "envelope",
    "laptop",
    "ledger",
    "vault",
    "signer",
    "marketplace",
    "losssink",
}

ENDPOINT_NODES = {
    "vault": "vault",
    "laptop": "laptop",
    "approver": "ledger",
    "signer": "signer",
    "node": "marketplace",
    "agent": "agent",
    "marketplace": "marketplace",
    "faucet": None,
}

HOP_LABELS = {
    "envelopes_fetched": "Vault → laptop: list of prepaid envelopes",
    "plan_sent_to_approver": "Laptop → Ledger: plan for the human to approve",
    "approval_received": "Ledger → laptop: signed approval",
    "approval_rejected": "Ledger: the human rejected the plan",
    "approval_sent_to_vault": "Laptop → vault: Ledger approval",
    "key_release_received": "Vault → laptop: envelope key release (key hidden)",
    "key_delivered_to_agent": (
        "Laptop → agent: envelope key handed over (key hidden)"
    ),
    "change_address_exported": "Vault → laptop: fresh change address",
    "utxos_selected": "Laptop: coins picked from main funds",
    "psbt_built": "Laptop: unsigned transaction built",
    "keys_released": (
        "Vault → laptop: signing keys for this payment only (keys hidden)"
    ),
    "keys_sent_to_signer": (
        "Laptop → signer: unsigned transaction and keys (keys hidden)"
    ),
    "signed_tx_received": "Signer → laptop: signed transaction",
    "verification_received": "Vault → laptop: verification result",
    "broadcast": "Laptop → network: verified transaction broadcast",
    "receive_addresses_exported": (
        "Vault → laptop: receive addresses for main funds"
    ),
    "main_funds_funded": "Faucet → vault: main funds deposited",
}

MARKETPLACE_TOOLS = {
    "search_products",
    "get_product_details",
    "suggest_products",
    "buy_product",
    "check_order",
}

LAPTOP_TOOLS = {"request_budget", "request_large_purchase"}

FLOW_ID_RE = re.compile(r"^[0-9A-Za-z_-]+$")


def _endpoint_node(name) -> str | None:
    if not isinstance(name, str):
        return None
    if name.startswith("agent:"):
        return "envelope"
    return ENDPOINT_NODES.get(name)


class Enricher:
    """Adds x-ray fields to raw events; tracks compromise sequences."""

    def __init__(self, flows_dir=None):
        self.flows_dir = Path(flows_dir) if flows_dir is not None else None
        self.seq = 0
        self.compromise_active = False

    def enrich(self, event: dict) -> dict:
        self.seq += 1
        event_type = event.get("type", "")
        if event_type == "compromise_started":
            self.compromise_active = True
        out = dict(event)
        out["seq"] = self.seq
        out["label"] = self._label(event)
        nodes = self._nodes(event)
        if nodes:
            out["nodes"] = nodes
        qr = self._qr(event)
        if qr:
            out["qr"] = qr
        alert = self._alert(event)
        if alert:
            out["alert"] = alert
        if event_type.startswith("compromise_"):
            out["simulation"] = True
        if event_type == "compromise_finished":
            self.compromise_active = False
        return out

    def _is_hop(self, event: dict) -> bool:
        payload = event.get("payload") or {}
        return (
            event.get("component") == "laptop"
            and isinstance(payload.get("flow_id"), str)
            and isinstance(payload.get("from"), str)
            and isinstance(payload.get("to"), str)
        )

    def _label(self, event: dict) -> str | None:
        if self._is_hop(event):
            label = HOP_LABELS.get(event.get("type"))
            if label is not None:
                return label
        return event.get("message")

    def _nodes(self, event: dict) -> dict | None:
        payload = event.get("payload") or {}
        event_type = event.get("type", "")
        component = event.get("component")
        if self._is_hop(event):
            src = _endpoint_node(payload["from"])
            dst = _endpoint_node(payload["to"])
            if src and dst:
                return {"at": src} if src == dst else {"from": src, "to": dst}
            only = dst or src
            return {"at": only} if only else None
        if event_type == "tool_call":
            tool = payload.get("tool")
            if tool in MARKETPLACE_TOOLS:
                return {"from": "agent", "to": "marketplace"}
            if tool in LAPTOP_TOOLS:
                return {"from": "agent", "to": "laptop"}
            if tool == "check_budget":
                return {"from": "agent", "to": "envelope"}
            return {"at": "agent"}
        if event_type == "wallet_loaded":
            return {"at": "envelope"}
        if event_type == "payment_sent":
            return {
                "from": "envelope",
                "to": "losssink" if self.compromise_active else "marketplace",
            }
        if event_type == "compromise_started":
            return {"at": "agent"}
        if event_type == "compromise_envelope_drained":
            return {"from": "envelope", "to": "losssink"}
        if event_type == "compromise_large_spend_requested":
            return {"from": "agent", "to": "laptop"}
        if event_type in (
            "compromise_large_spend_blocked",
            "compromise_large_spend_approved",
        ):
            return {"at": "ledger"}
        if event_type == "compromise_finished":
            return {"at": "losssink"}
        if component == "approver":
            return {"at": "ledger"}
        node = _endpoint_node(component)
        if node:
            return {"at": node}
        return None

    def _qr(self, event: dict) -> dict | None:
        if self.flows_dir is None or not self._is_hop(event):
            return None
        payload = event.get("payload") or {}
        flow_id = payload.get("flow_id")
        hop_index = payload.get("hop")
        if (
            not isinstance(flow_id, str)
            or not FLOW_ID_RE.fullmatch(flow_id)
            or not isinstance(hop_index, int)
        ):
            return None
        try:
            doc = json.loads(
                (self.flows_dir / f"{flow_id}.json").read_text()
            )
        except (OSError, ValueError):
            return None
        for hop in doc.get("hops") or []:
            if hop.get("index") != hop_index:
                continue
            stored = hop.get("payload")
            if not isinstance(stored, dict):
                return None
            return {
                "type": stored.get("type"),
                "parts": stored.get("parts"),
                "redacted": bool(hop.get("redacted")),
            }
        return None

    def _alert(self, event: dict) -> dict | None:
        if event.get("component") != "vault":
            return None
        payload = event.get("payload") or {}
        if event.get("type") == "verification_failed":
            return {
                "level": "error",
                "title": "Vault blocked this transaction",
                "reasons": payload.get("reasons"),
            }
        if event.get("type") == "release_refused":
            return {
                "level": "error",
                "title": "Vault refused to release keys",
                "reasons": [payload.get("reason")],
            }
        return None
