"""Minimal stdlib-only JSON-RPC client for the local regtest bitcoind."""

from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable

DEFAULT_RPC_URL = "http://127.0.0.1:18443"
DEFAULT_RPC_USER = "satchel"
DEFAULT_RPC_PASSWORD = "satchel"
FAUCET_WALLET = "faucet"
COIN = 100_000_000
COINBASE_MATURITY = 100


def btc_to_sats(amount: Decimal | str) -> int:
    sats = Decimal(amount) * COIN
    if sats != sats.to_integral_value():
        raise ValueError(f"{amount} BTC is not a whole number of satoshis")
    return int(sats)


def sats_to_btc(sats: int) -> str:
    return f"{Decimal(sats) / COIN:.8f}"


class RPCError(Exception):
    def __init__(self, code: int, message: str):
        super().__init__(f"RPC error {code}: {message}")
        self.code = code
        self.message = message


class NodeUnavailable(ConnectionError):
    pass


class NotRegtestError(RuntimeError):
    pass


@dataclass(frozen=True)
class Utxo:
    txid: str
    vout: int
    address: str
    amount_sats: int
    script_pubkey: str
    height: int
    coinbase: bool


class RegtestNode:
    """Client for the local regtest bitcoind. Refuses to talk to any other chain."""

    def __init__(
        self,
        url: str = DEFAULT_RPC_URL,
        user: str = DEFAULT_RPC_USER,
        password: str = DEFAULT_RPC_PASSWORD,
        faucet_wallet: str = FAUCET_WALLET,
        timeout: float = 30.0,
    ):
        self.url = url.rstrip("/")
        self.user = user
        self.password = password
        self.faucet_wallet = faucet_wallet
        self.timeout = timeout
        self._request_id = 0
        self._checked_regtest = False

    @classmethod
    def from_env(cls) -> RegtestNode:
        return cls(
            url=os.environ.get("BITCOIND_RPC_URL", DEFAULT_RPC_URL),
            user=os.environ.get("BITCOIND_RPC_USER", DEFAULT_RPC_USER),
            password=os.environ.get("BITCOIND_RPC_PASSWORD", DEFAULT_RPC_PASSWORD),
        )

    def _post(self, path: str, payload: dict) -> dict:
        credentials = base64.b64encode(f"{self.user}:{self.password}".encode()).decode()
        request = urllib.request.Request(
            self.url + path,
            data=json.dumps(payload).encode(),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Basic {credentials}",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read(), parse_float=Decimal)
        except urllib.error.HTTPError as exc:
            try:
                data = json.loads(exc.read(), parse_float=Decimal)
            except (ValueError, OSError):
                data = None
            if isinstance(data, dict) and data.get("error") is not None:
                return data
            if exc.code == 401:
                raise RPCError(401, "authentication failed") from exc
            raise RPCError(exc.code, f"HTTP {exc.code}: {exc.reason}") from exc
        except (urllib.error.URLError, OSError) as exc:
            raise NodeUnavailable(f"cannot reach bitcoind at {self.url}: {exc}") from exc

    def _rpc(self, method: str, params: list | None = None, wallet: str | None = None):
        self._request_id += 1
        payload = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": method,
            "params": list(params) if params else [],
        }
        path = "" if wallet is None else f"/wallet/{urllib.parse.quote(wallet, safe='')}"
        response = self._post(path, payload)
        if response.get("error") is not None:
            error = response["error"]
            raise RPCError(error.get("code", -1), error.get("message", "unknown error"))
        return response.get("result")

    def call(self, method: str, *params, wallet: str | None = None):
        """Call any RPC method; refuses to proceed unless the node is on regtest."""
        if not self._checked_regtest:
            info = self._rpc("getblockchaininfo")
            if info.get("chain") != "regtest":
                raise NotRegtestError(
                    f"node at {self.url} is on chain {info.get('chain')!r}, expected regtest"
                )
            self._checked_regtest = True
        return self._rpc(method, list(params), wallet=wallet)

    def mine_blocks(self, count: int, address: str) -> list[str]:
        return self.call("generatetoaddress", count, address)

    def send_to_address(self, address: str, amount_sats: int) -> str:
        if isinstance(amount_sats, bool) or not isinstance(amount_sats, int) or amount_sats <= 0:
            raise ValueError(f"amount_sats must be a positive integer, got {amount_sats!r}")
        return self.call(
            "sendtoaddress", address, sats_to_btc(amount_sats), wallet=self.faucet_wallet
        )

    def list_unspent(self, addresses: Iterable[str]) -> list[Utxo]:
        """UTXOs paying to the given addresses.

        Scans the confirmed UTXO set only; mempool transactions are not included.
        """
        unique = list(dict.fromkeys(addresses))
        if not unique:
            return []
        scripts = {}
        for address in unique:
            info = self.call("validateaddress", address)
            if not info.get("isvalid"):
                raise ValueError(f"invalid address: {address}")
            scripts[info["scriptPubKey"]] = address
        result = self.call("scantxoutset", "start", [f"addr({a})" for a in unique])
        if not result.get("success"):
            raise RPCError(-1, "scantxoutset failed")
        utxos = []
        for entry in result["unspents"]:
            address = scripts.get(entry["scriptPubKey"])
            if address is None:
                continue
            utxos.append(
                Utxo(
                    txid=entry["txid"],
                    vout=entry["vout"],
                    address=address,
                    amount_sats=btc_to_sats(entry["amount"]),
                    script_pubkey=entry["scriptPubKey"],
                    height=entry["height"],
                    coinbase=entry["coinbase"],
                )
            )
        utxos.sort(key=lambda u: (u.height, u.txid, u.vout))
        return utxos

    def broadcast(self, raw_tx_hex: str) -> str:
        return self.call("sendrawtransaction", raw_tx_hex)

    def get_transaction(self, txid: str) -> dict:
        return self.call("getrawtransaction", txid, True)

    def is_unspent(self, txid: str, vout: int, include_mempool: bool = True) -> bool:
        return self.call("gettxout", txid, vout, include_mempool) is not None

    def faucet_address(self) -> str:
        return self.call("getnewaddress", wallet=self.faucet_wallet)

    def faucet_balance_sats(self) -> int:
        return btc_to_sats(self.call("getbalance", wallet=self.faucet_wallet))

    def ensure_faucet(self, min_balance_sats: int = COIN) -> int:
        """Create or load the faucet wallet and mine mature coinbase if it is low."""
        if self.faucet_wallet not in self.call("listwallets"):
            names = {w["name"] for w in self.call("listwalletdir")["wallets"]}
            if self.faucet_wallet in names:
                self.call("loadwallet", self.faucet_wallet)
            else:
                self.call("createwallet", self.faucet_wallet)
        balance = self.faucet_balance_sats()
        if balance < min_balance_sats:
            self.mine_blocks(COINBASE_MATURITY + 1, self.faucet_address())
            balance = self.faucet_balance_sats()
        return balance

    def fund_address(self, address: str, amount_sats: int, confirm: bool = True) -> str:
        txid = self.send_to_address(address, amount_sats)
        if confirm:
            self.mine_blocks(1, self.faucet_address())
        return txid
