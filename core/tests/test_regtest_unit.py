"""Unit tests for RegtestNode; _post is faked so no network is needed."""

from decimal import Decimal

import pytest

from satchel_core.regtest import (
    COIN,
    NotRegtestError,
    RPCError,
    RegtestNode,
    Utxo,
    btc_to_sats,
    sats_to_btc,
)


class FakeRPC:
    """Stands in for RegtestNode._post; records (path, method, params)."""

    def __init__(self, results: dict | None = None, chain: str = "regtest"):
        self.calls: list[tuple[str, str, list]] = []
        self.results = {"getblockchaininfo": {"chain": chain}, **(results or {})}

    def __call__(self, path: str, payload: dict) -> dict:
        self.calls.append((path, payload["method"], payload["params"]))
        entry = self.results[payload["method"]]
        if callable(entry):
            entry = entry(payload["params"])
        if isinstance(entry, RPCError):
            return {
                "jsonrpc": "2.0",
                "id": payload["id"],
                "result": None,
                "error": {"code": entry.code, "message": entry.message},
            }
        return {"jsonrpc": "2.0", "id": payload["id"], "result": entry, "error": None}


def make_node(fake: FakeRPC) -> RegtestNode:
    node = RegtestNode()
    node._post = fake
    return node


@pytest.mark.parametrize("chain", ["main", "test", "signet"])
def test_non_regtest_chain_rejected(chain):
    fake = FakeRPC(chain=chain)
    node = make_node(fake)
    with pytest.raises(NotRegtestError):
        node.faucet_address()
    assert [method for _, method, _ in fake.calls] == ["getblockchaininfo"]


def test_chain_check_runs_once():
    fake = FakeRPC({"getblockcount": 42})
    node = make_node(fake)
    node.call("getblockcount")
    node.call("getblockcount")
    methods = [method for _, method, _ in fake.calls]
    assert methods.count("getblockchaininfo") == 1
    assert methods.count("getblockcount") == 2


def test_btc_to_sats():
    assert btc_to_sats(Decimal("0.0015")) == 150_000
    assert btc_to_sats("21000000") == 2_100_000_000_000_000
    with pytest.raises(ValueError):
        btc_to_sats(Decimal("0.000000001"))


def test_sats_to_btc():
    assert sats_to_btc(150_000) == "0.00150000"
    assert sats_to_btc(COIN) == "1.00000000"


@pytest.mark.parametrize("bad", [0, -1, 1.5, True])
def test_send_to_address_rejects_bad_amounts(bad):
    fake = FakeRPC()
    node = make_node(fake)
    with pytest.raises(ValueError):
        node.send_to_address("bcrt1qwhatever", bad)
    assert fake.calls == []


def test_send_to_address_posts_string_amount():
    fake = FakeRPC({"sendtoaddress": "txid123"})
    node = make_node(fake)
    assert node.send_to_address("bcrt1qwhatever", 150_000) == "txid123"
    assert fake.calls[-1] == (
        "/wallet/faucet",
        "sendtoaddress",
        ["bcrt1qwhatever", "0.00150000"],
    )


def test_list_unspent_empty():
    fake = FakeRPC()
    node = make_node(fake)
    assert node.list_unspent([]) == []
    assert fake.calls == []


def test_list_unspent_invalid_address():
    fake = FakeRPC({"validateaddress": {"isvalid": False, "scriptPubKey": ""}})
    node = make_node(fake)
    with pytest.raises(ValueError, match="bcrt1qbad"):
        node.list_unspent(["bcrt1qbad"])


def test_list_unspent_maps_and_sorts():
    scripts = {"bcrt1qa": "0014aaaa", "bcrt1qb": "0014bbbb"}
    fake = FakeRPC(
        {
            "validateaddress": lambda p: {
                "isvalid": True,
                "scriptPubKey": scripts[p[0]],
            },
            "scantxoutset": {
                "success": True,
                "unspents": [
                    {
                        "txid": "t2",
                        "vout": 0,
                        "scriptPubKey": "0014bbbb",
                        "amount": Decimal("0.002"),
                        "height": 120,
                        "coinbase": False,
                    },
                    {
                        "txid": "t1",
                        "vout": 1,
                        "scriptPubKey": "0014aaaa",
                        "amount": Decimal("0.0015"),
                        "height": 110,
                        "coinbase": True,
                    },
                ],
            },
        }
    )
    node = make_node(fake)
    utxos = node.list_unspent(["bcrt1qa", "bcrt1qb", "bcrt1qa"])
    assert utxos == [
        Utxo(
            txid="t1",
            vout=1,
            address="bcrt1qa",
            amount_sats=150_000,
            script_pubkey="0014aaaa",
            height=110,
            coinbase=True,
        ),
        Utxo(
            txid="t2",
            vout=0,
            address="bcrt1qb",
            amount_sats=200_000,
            script_pubkey="0014bbbb",
            height=120,
            coinbase=False,
        ),
    ]
    validate_calls = [c for c in fake.calls if c[1] == "validateaddress"]
    assert len(validate_calls) == 2
    scan = next(c for c in fake.calls if c[1] == "scantxoutset")
    assert scan[0] == ""
    assert scan[2] == ["start", ["addr(bcrt1qa)", "addr(bcrt1qb)"]]


def test_rpc_error_raises():
    fake = FakeRPC({"sendtoaddress": RPCError(-6, "Insufficient funds")})
    node = make_node(fake)
    with pytest.raises(RPCError) as exc:
        node.send_to_address("bcrt1qwhatever", 1_000)
    assert exc.value.code == -6
    assert exc.value.message == "Insufficient funds"
