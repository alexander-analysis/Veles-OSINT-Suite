"""Ethereum JSON-RPC (public node, keyless): balances, blocks, ERC-20 transfer logs.

Default endpoint is PublicNode; any standard RPC URL works (``ETHEREUM_RPC_URL``
in .env).  Log queries are kept inside the ~5000-block window a non-archive
node serves.
"""

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx

from app.config import settings
from app.data.crypto_labels import STABLECOINS
from app.utils.logger import logger
from app.utils.time import from_unix_seconds

log = logger.bind(component="ethereum")

DEFAULT_RPC = "https://ethereum-rpc.publicnode.com"
TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
WEI = 10**18
MAX_LOG_SPAN = 4500
HEX_ADDRESS = re.compile(r"0x[0-9a-fA-F]{40}")


@dataclass
class EthTransfer:
    tx_hash: str
    block_number: int
    timestamp: datetime | None
    from_address: str
    to_address: str | None
    amount: float
    token: str  # ETH, USDT, USDC, DAI
    log_index: int | None = None


def _hex_int(value: str | None) -> int:
    return int(value, 16) if value else 0


def topic_for(address: str) -> str | None:
    """32-byte topic for an address; ``None`` for anything that is not ``0x`` + 40 hex characters."""
    if not HEX_ADDRESS.fullmatch(address or ""):
        return None
    return "0x" + address[2:].lower().rjust(64, "0")


def address_from_topic(topic: str) -> str:
    return "0x" + topic[-40:].lower()


class EthereumRPC:
    def __init__(self, url: str | None = None) -> None:
        self.url = url or settings.key("ETHEREUM_RPC_URL") or DEFAULT_RPC
        self.calls = 0

    async def _call(self, payload: Any, timeout: float = 60) -> Any:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(self.url, json=payload)
        self.calls += 1
        response.raise_for_status()
        data = response.json()
        if isinstance(data, dict) and data.get("error"):
            raise RuntimeError(f"rpc error: {data['error'].get('message')}")
        return data

    async def block_number(self) -> int:
        return _hex_int((await self._call({"jsonrpc": "2.0", "id": 1, "method": "eth_blockNumber", "params": []}))["result"])

    async def balances(self, addresses: list[str]) -> dict[str, tuple[float, int]]:
        """{address: (balance_eth, nonce)} through one batched request."""
        if not addresses:
            return {}
        batch = []
        for i, address in enumerate(addresses):
            batch.append({"jsonrpc": "2.0", "id": 2 * i, "method": "eth_getBalance", "params": [address, "latest"]})
            batch.append({"jsonrpc": "2.0", "id": 2 * i + 1, "method": "eth_getTransactionCount", "params": [address, "latest"]})
        results = await self._call(batch)
        by_id = {item["id"]: item.get("result") for item in results if isinstance(item, dict)}
        out: dict[str, tuple[float, int]] = {}
        for i, address in enumerate(addresses):
            balance, nonce = by_id.get(2 * i), by_id.get(2 * i + 1)
            if balance is not None:
                out[address] = (_hex_int(balance) / WEI, _hex_int(nonce))
        return out

    async def block(self, number: int, full: bool = True) -> dict[str, Any] | None:
        data = await self._call({"jsonrpc": "2.0", "id": 1, "method": "eth_getBlockByNumber", "params": [hex(number), full]}, timeout=90)
        return data.get("result")

    @staticmethod
    def native_transfers(block: dict[str, Any], min_eth: float = 0.0) -> list[EthTransfer]:
        ts = from_unix_seconds(_hex_int(block.get("timestamp"))) if block.get("timestamp") else None
        number = _hex_int(block.get("number"))
        out = []
        for tx in block.get("transactions", []):
            if not isinstance(tx, dict):
                continue
            value = _hex_int(tx.get("value")) / WEI
            if value >= min_eth:
                out.append(EthTransfer(tx["hash"], number, ts, tx["from"].lower(), (tx.get("to") or "").lower() or None, value, "ETH"))
        return out

    async def stablecoin_logs(self, from_block: int, to_block: int, from_topics: list[str] | None = None, to_topics: list[str] | None = None) -> list[EthTransfer]:
        """ERC-20 Transfer events of USDT/USDC/DAI, optionally restricted to senders / recipients."""
        if to_block - from_block > MAX_LOG_SPAN:
            from_block = to_block - MAX_LOG_SPAN
        topics: list[Any] = [TRANSFER_TOPIC]
        if from_topics or to_topics:
            topics.append(from_topics or None)
            if to_topics:
                topics.append(to_topics)
        params = {"fromBlock": hex(from_block), "toBlock": hex(to_block), "address": list(STABLECOINS), "topics": topics}
        data = await self._call({"jsonrpc": "2.0", "id": 1, "method": "eth_getLogs", "params": [params]}, timeout=90)
        out = []
        for entry in data.get("result", []) or []:
            symbol, decimals = STABLECOINS.get(entry["address"].lower(), ("?", 18))
            if len(entry.get("topics", [])) < 3:
                continue
            out.append(
                EthTransfer(
                    tx_hash=entry["transactionHash"],
                    block_number=_hex_int(entry.get("blockNumber")),
                    timestamp=None,
                    from_address=address_from_topic(entry["topics"][1]),
                    to_address=address_from_topic(entry["topics"][2]),
                    amount=_hex_int(entry.get("data")) / 10**decimals,
                    token=symbol,
                    log_index=_hex_int(entry.get("logIndex")),
                )
            )
        return out

    async def block_timestamp(self, number: int) -> datetime | None:
        block = await self.block(number, full=False)
        return from_unix_seconds(_hex_int(block["timestamp"])) if block else None
