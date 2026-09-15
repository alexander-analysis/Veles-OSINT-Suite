"""Bitcoin address / transaction lookups through the Blockstream Esplora API (keyless).

Also: BTC/USD from mempool.space and the blockchain.com unconfirmed-transaction
websocket used for the real-time whale / sanctioned-address watch.
"""

import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable

import httpx
import websockets

from app.utils.logger import logger
from app.utils.time import from_unix_seconds, utcnow

log = logger.bind(component="blockstream")

ESPLORA = "https://blockstream.info/api"
MEMPOOL_PRICES = "https://mempool.space/api/v1/prices"
BLOCKCHAIN_WS = "wss://ws.blockchain.info/inv"
UA = {"User-Agent": "VELES-OSINT/1.0 (sanctions research)"}
SATS = 100_000_000


@dataclass
class BtcAddressStats:
    address: str
    received_btc: float
    spent_btc: float
    tx_count: int
    mempool_tx_count: int

    @property
    def balance_btc(self) -> float:
        return round(self.received_btc - self.spent_btc, 8)


@dataclass
class BtcTransfer:
    txid: str
    timestamp: datetime | None
    block_height: int | None
    inputs: list[tuple[str, float]]  # (address, btc)
    outputs: list[tuple[str, float]]
    fee_btc: float
    total_out_btc: float
    counterparties: list[str] = field(default_factory=list)


async def address_stats(address: str, client: httpx.AsyncClient | None = None) -> BtcAddressStats:
    async with (client or httpx.AsyncClient(timeout=30, headers=UA)) as c:
        response = await c.get(f"{ESPLORA}/address/{address}")
        response.raise_for_status()
        data = response.json()
    chain, mempool = data["chain_stats"], data["mempool_stats"]
    return BtcAddressStats(
        address=address,
        received_btc=chain["funded_txo_sum"] / SATS,
        spent_btc=chain["spent_txo_sum"] / SATS,
        tx_count=chain["tx_count"],
        mempool_tx_count=mempool["tx_count"],
    )


def parse_transaction(tx: dict[str, Any], focus: str | None = None) -> BtcTransfer:
    inputs = [(vin.get("prevout", {}).get("scriptpubkey_address") or "coinbase", (vin.get("prevout", {}).get("value") or 0) / SATS) for vin in tx.get("vin", [])]
    outputs = [(vout.get("scriptpubkey_address") or "op_return", (vout.get("value") or 0) / SATS) for vout in tx.get("vout", [])]
    status = tx.get("status", {})
    counterparties = sorted({a for a, _ in inputs + outputs if a not in (focus, "coinbase", "op_return")}) if focus else []
    return BtcTransfer(
        txid=tx["txid"],
        timestamp=from_unix_seconds(status["block_time"]) if status.get("block_time") else None,
        block_height=status.get("block_height"),
        inputs=inputs,
        outputs=outputs,
        fee_btc=(tx.get("fee") or 0) / SATS,
        total_out_btc=round(sum(v for _, v in outputs), 8),
        counterparties=counterparties,
    )


async def address_transactions(address: str, client: httpx.AsyncClient | None = None) -> list[BtcTransfer]:
    """Newest 25 confirmed + mempool transactions touching the address."""
    async with (client or httpx.AsyncClient(timeout=30, headers=UA)) as c:
        response = await c.get(f"{ESPLORA}/address/{address}/txs")
        response.raise_for_status()
        rows = response.json()
    return [parse_transaction(tx, address) for tx in rows]


async def btc_usd() -> float | None:
    try:
        async with httpx.AsyncClient(timeout=15, headers=UA) as c:
            response = await c.get(MEMPOOL_PRICES)
            response.raise_for_status()
            return float(response.json()["USD"])
    except Exception as exc:  # noqa: BLE001
        log.debug("btc price unavailable: {}", exc)
        return None


class BitcoinMempoolStream:
    """blockchain.com ``unconfirmed_sub`` firehose (~3-10 tx/s).

    ``on_tx`` receives ``(txid, total_btc, input_addresses, output_addresses, outputs)`` for
    every unconfirmed transaction; the caller decides what is interesting.
    """

    def __init__(self, on_tx: Callable[[str, float, list[str], list[tuple[str, float]]], None]) -> None:
        self.on_tx = on_tx
        self.connected = False
        self.messages = 0
        self.last_message_at: datetime | None = None
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.get_event_loop().create_task(self._run())

    def stop(self) -> None:
        if self._task:
            self._task.cancel()

    async def _run(self) -> None:
        backoff = 5
        while True:
            try:
                async with websockets.connect(BLOCKCHAIN_WS, open_timeout=20, ping_interval=30, ping_timeout=60, max_size=4_000_000) as ws:
                    await ws.send(json.dumps({"op": "unconfirmed_sub"}))
                    self.connected = True
                    backoff = 5
                    log.info("unconfirmed-transaction stream connected")
                    async for raw in ws:
                        message = json.loads(raw)
                        if message.get("op") != "utx":
                            continue
                        tx = message["x"]
                        self.messages += 1
                        self.last_message_at = utcnow()
                        inputs = [i.get("prev_out", {}).get("addr") for i in tx.get("inputs", [])]
                        outputs = [(o.get("addr"), (o.get("value") or 0) / SATS) for o in tx.get("out", [])]
                        total = sum(v for _, v in outputs)
                        try:
                            self.on_tx(tx["hash"], total, [a for a in inputs if a], outputs)
                        except Exception as exc:  # noqa: BLE001 - a bad callback must not kill the stream
                            log.warning("stream callback failed: {}", exc)
            except asyncio.CancelledError:
                self.connected = False
                raise
            except Exception as exc:  # noqa: BLE001
                self.connected = False
                log.warning("unconfirmed stream dropped ({}); reconnecting in {} s", exc, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 300)

    def status(self) -> dict[str, Any]:
        return {"connected": self.connected, "messages": self.messages, "last_message_at": self.last_message_at}
