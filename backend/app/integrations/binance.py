"""Binance market data.

* Spot OHLCV through ccxt (USDT-quoted pairs).
* Futures liquidations through the public ``!forceOrder@arr`` WebSocket
  stream (there is no REST endpoint for this any more).  Events are buffered
  in memory and drained by the market bot's cascade analysis.
"""

import asyncio
import json
from collections import deque
from datetime import datetime

import websockets

from app.config import settings
from app.integrations.exchange_ccxt import ExchangeClient, ExchangeSpec
from app.utils.logger import logger
from app.utils.time import from_unix_ms

log = logger.bind(component="market")

SPEC = ExchangeSpec(name="binance", ccxt_id="binance", quote="USDT")
LIQUIDATION_STREAM_URL = "wss://fstream.binance.com/ws/!forceOrder@arr"


def create_client() -> ExchangeClient:
    return ExchangeClient(SPEC, api_key=settings.BINANCE_API_KEY if settings.BINANCE_API_KEY != "your_key_here" else "")


class LiquidationEvent(dict):
    """``{"asset", "exchange", "side", "price", "quantity", "usd", "timestamp"}``."""


class LiquidationStream:
    """Long-lived consumer of Binance futures liquidation orders."""

    def __init__(self, assets: set[str], maxlen: int = 20000) -> None:
        self.assets = {asset.upper() for asset in assets}
        self.events: deque[LiquidationEvent] = deque(maxlen=maxlen)
        self.connected = False
        self.last_event_at: datetime | None = None
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run(), name="binance-liquidations")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()

    def drain(self) -> list[LiquidationEvent]:
        """Return and clear buffered events."""
        events = list(self.events)
        self.events.clear()
        return events

    def _parse(self, message: str) -> LiquidationEvent | None:
        order = json.loads(message).get("o", {})
        symbol = order.get("s", "")  # e.g. BTCUSDT
        asset = symbol[:-4] if symbol.endswith("USDT") else None
        if not asset or asset not in self.assets:
            return None
        price = float(order.get("ap") or order.get("p") or 0)
        quantity = float(order.get("z") or order.get("q") or 0)
        return LiquidationEvent(
            asset=asset,
            exchange="binance",
            side=order.get("S", "").lower(),  # SELL = long liquidated, BUY = short liquidated
            price=price,
            quantity=quantity,
            usd=price * quantity,
            timestamp=from_unix_ms(order.get("T", 0)),
        )

    async def _run(self) -> None:
        delay = 5
        while True:
            try:
                async with websockets.connect(LIQUIDATION_STREAM_URL, ping_interval=20, ping_timeout=20) as socket:
                    self.connected = True
                    delay = 5
                    log.info("binance liquidation stream connected")
                    async for message in socket:
                        event = self._parse(message)
                        if event:
                            self.events.append(event)
                            self.last_event_at = event["timestamp"]
            except asyncio.CancelledError:
                self.connected = False
                raise
            except Exception as exc:  # noqa: BLE001 - reconnect on anything
                self.connected = False
                log.warning("binance liquidation stream error: {} - reconnecting in {}s", exc, delay)
                await asyncio.sleep(delay)
                delay = min(delay * 2, 300)
