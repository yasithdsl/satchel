"""Enricher: nodes, labels, qr attachments, alerts, simulation flags."""

import json

import pytest

from satchel_core.payloads import MessageType, Payload
from satchel_laptop.flows import FlowRecorder
from satchel_xray.enrich import Enricher, HOP_LABELS


def event(component, etype, payload=None, message="a message"):
    return {
        "id": "id-" + etype,
        "ts": "2026-10-12T20:00:00.000+00:00",
        "component": component,
        "type": etype,
        "message": message,
        "payload": payload,
    }


def hop(etype, src, dst, flow_id="flow1", index=0):
    return event(
        "laptop",
        etype,
        {
            "flow_id": flow_id,
            "flow": "grant",
            "hop": index,
            "from": src,
            "to": dst,
            "payload_type": None,
        },
        message=f"flow {flow_id} hop {index}: {src} -> {dst} ({etype})",
    )


def enricher(tmp_path=None):
    return Enricher(flows_dir=(tmp_path or "") and tmp_path)


def test_seq_and_label_for_hops(tmp_path):
    en = Enricher()
    out = en.enrich(hop("plan_sent_to_approver", "laptop", "approver"))
    assert out["seq"] == 1
    assert out["label"] == "Laptop → Ledger: plan for the human to approve"
    out = en.enrich(event("agent", "tool_call", {"tool": "check_budget"}))
    assert out["seq"] == 2


@pytest.mark.parametrize("name,label", sorted(HOP_LABELS.items()))
def test_every_hop_label(name, label):
    en = Enricher()
    out = en.enrich(hop(name, "laptop", "vault"))
    assert out["label"] == label


def test_hop_endpoint_mappings():
    en = Enricher()
    assert en.enrich(hop("envelopes_fetched", "vault", "laptop"))[
        "nodes"
    ] == {"from": "vault", "to": "laptop"}
    assert en.enrich(hop("plan_sent_to_approver", "laptop", "approver"))[
        "nodes"
    ] == {"from": "laptop", "to": "ledger"}
    assert en.enrich(
        hop("key_delivered_to_agent", "laptop", "agent:shopper-7")
    )["nodes"] == {"from": "laptop", "to": "envelope"}
    assert en.enrich(hop("broadcast", "laptop", "node"))["nodes"] == {
        "from": "laptop",
        "to": "marketplace",
    }
    assert en.enrich(hop("psbt_built", "laptop", "laptop"))["nodes"] == {
        "at": "laptop"
    }
    assert en.enrich(hop("main_funds_funded", "faucet", "vault"))[
        "nodes"
    ] == {"at": "vault"}
    assert en.enrich(hop("keys_sent_to_signer", "laptop", "signer"))[
        "nodes"
    ] == {"from": "laptop", "to": "signer"}


def test_tool_call_routes():
    en = Enricher()
    for tool in (
        "search_products",
        "get_product_details",
        "suggest_products",
        "buy_product",
        "check_order",
    ):
        out = en.enrich(
            event("agent", "tool_call", {"tool": tool, "input": {}})
        )
        assert out["nodes"] == {"from": "agent", "to": "marketplace"}, tool
    for tool in ("request_budget", "request_large_purchase"):
        out = en.enrich(
            event("agent", "tool_call", {"tool": tool, "input": {}})
        )
        assert out["nodes"] == {"from": "agent", "to": "laptop"}, tool
    out = en.enrich(
        event("agent", "tool_call", {"tool": "check_budget", "input": {}})
    )
    assert out["nodes"] == {"from": "agent", "to": "envelope"}


def test_wallet_loaded_and_payment_sent():
    en = Enricher()
    assert en.enrich(event("agent", "wallet_loaded"))["nodes"] == {
        "at": "envelope"
    }
    assert en.enrich(event("agent", "payment_sent"))["nodes"] == {
        "from": "envelope",
        "to": "marketplace",
    }


def test_payment_sent_during_compromise_goes_to_loss_sink():
    en = Enricher()
    en.enrich(event("agent", "compromise_started", {}))
    assert en.enrich(event("agent", "payment_sent"))["nodes"] == {
        "from": "envelope",
        "to": "losssink",
    }
    en.enrich(event("agent", "compromise_finished", {}))
    assert en.enrich(event("agent", "payment_sent"))["nodes"] == {
        "from": "envelope",
        "to": "marketplace",
    }


def test_component_fallback_routes():
    en = Enricher()
    assert en.enrich(event("approver", "approval_requested"))["nodes"] == {
        "at": "ledger"
    }
    assert en.enrich(event("approver", "approval_granted"))["nodes"] == {
        "at": "ledger"
    }
    assert en.enrich(event("vault", "release_requested"))["nodes"] == {
        "at": "vault"
    }
    assert en.enrich(event("vault", "envelope_released"))["nodes"] == {
        "at": "vault"
    }
    assert en.enrich(event("signer", "random_nonce_enabled"))["nodes"] == {
        "at": "signer"
    }
    assert en.enrich(event("marketplace", "order_paid"))["nodes"] == {
        "at": "marketplace"
    }
    assert en.enrich(event("agent", "payment_rejected"))["nodes"] == {
        "at": "agent"
    }
    assert en.enrich(event("agent", "payment_failed"))["nodes"] == {
        "at": "agent"
    }
    assert en.enrich(event("agent", "large_purchase_notice"))["nodes"] == {
        "at": "agent"
    }
    out = en.enrich(event("syslog", "weird"))
    assert "nodes" not in out


def test_compromise_events_simulation_and_nodes():
    en = Enricher()
    cases = [
        ("compromise_started", {"at": "agent"}),
        ("compromise_envelope_drained", {"from": "envelope", "to": "losssink"}),
        ("compromise_large_spend_requested", {"from": "agent", "to": "laptop"}),
        ("compromise_large_spend_blocked", {"at": "ledger"}),
        ("compromise_large_spend_approved", {"at": "ledger"}),
        ("compromise_finished", {"at": "losssink"}),
    ]
    for etype, nodes in cases:
        out = en.enrich(event("agent", etype, {}))
        assert out["nodes"] == nodes, etype
        assert out["simulation"] is True, etype
    out = en.enrich(event("agent", "tool_call", {"tool": "check_budget"}))
    assert "simulation" not in out


def test_label_falls_back_to_message():
    en = Enricher()
    out = en.enrich(event("vault", "release_requested", message="hello"))
    assert out["label"] == "hello"
    unknown_hop = hop("unlisted_hop", "laptop", "vault")
    out = en.enrich(unknown_hop)
    assert out["label"] == unknown_hop["message"]


def test_qr_attaches_redacted_parts_without_wif(tmp_path):
    recorder = FlowRecorder("grant", tmp_path)
    secret_wif = "cTsecretwifsecretwifsecretwifsecretwifsecretwif123456"
    release = Payload(
        MessageType.KEY_RELEASE,
        {
            "kind": "envelope",
            "envelope_index": 0,
            "address": "bcrt1qx",
            "wif": secret_wif,
        },
    )
    recorder.hop("key_release_received", "vault", "laptop", release)
    en = Enricher(flows_dir=tmp_path / "flows")
    out = en.enrich(
        hop("key_release_received", "vault", "laptop", recorder.flow_id)
    )
    assert out["qr"]["type"] == "key_release"
    assert out["qr"]["parts"]
    assert out["qr"]["redacted"] is True
    assert secret_wif not in json.dumps(out)


def test_qr_missing_flow_or_hop(tmp_path):
    en = Enricher(flows_dir=tmp_path / "flows")
    out = en.enrich(hop("plan_sent_to_approver", "laptop", "approver"))
    assert "qr" not in out
    recorder = FlowRecorder("grant", tmp_path)
    recorder.hop("utxos_selected", "laptop", "laptop", None, {"x": 1})
    out = en.enrich(
        hop("utxos_selected", "laptop", "laptop", recorder.flow_id)
    )
    assert "qr" not in out
    out = en.enrich(
        hop("utxos_selected", "laptop", "laptop", recorder.flow_id, 9)
    )
    assert "qr" not in out


def test_alerts():
    en = Enricher()
    out = en.enrich(
        event(
            "vault",
            "verification_failed",
            {"txid": "t", "reasons": ["bad sig", "bad output"]},
        )
    )
    assert out["alert"] == {
        "level": "error",
        "title": "Vault blocked this transaction",
        "reasons": ["bad sig", "bad output"],
    }
    out = en.enrich(
        event("vault", "release_refused", {"reason": "bad approval"})
    )
    assert out["alert"] == {
        "level": "error",
        "title": "Vault refused to release keys",
        "reasons": ["bad approval"],
    }
    out = en.enrich(
        event("vault", "verification_passed", {"txid": "t", "reasons": []})
    )
    assert "alert" not in out
    out = en.enrich(
        event("laptop", "verification_failed", {"reasons": ["x"]})
    )
    assert "alert" not in out
