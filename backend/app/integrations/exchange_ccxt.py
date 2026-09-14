"""Unified exchange access through ccxt (async).

One ``ExchangeClient`` per exchange, created lazily and kept for the life of
the process so markets are loaded once.  Every call is rate-limited by ccxt,
retried with back-off on transient errors, and logged.
"""

import asyncio
from dataclasses import dataclass, field

import ccxt.async_support as ccxt

from app.utils.logger import logger

log = logger.bind(component="market")

TRANSIENT_ERRORS = (ccxt.NetworkError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout, ccxt.DDoSProtection)


@dataclass
class ExchangeSpec:
    """How VELES talks to one exchange."""

    name: str  # our identifier: binance, kraken, coinbase
    ccxt_id: str  # ccxt class name
    quote: str  # quote currency for spot pairs (USDT or USD)
    symbol_overrides: dict[str, str] = field(default_factory=dict)  # asset -> full symbol
    options: dict = field(default_factory=dict)

    def symbol_for(self, asset: str) -> str:
        return self.symbol_overrides.get(asset, f"{asset}/{self.quote}")


class ExchangeClient:
    def __init__(self, spec: ExchangeSpec, api_key: str = "", secret: str = "") -> None:
        self.spec = spec
        config = {"enableRateLimit": True, "options": dict(spec.options)}
        if api_key:
            config["apiKey"] = api_key
        if secret:
            config["secret"] = secret
        self.exchange = getattr(ccxt, spec.ccxt_id)(config)
        self._markets_loaded = False
        self._lock = asyncio.Lock()

    @property
    def name(self) -> str:
        return self.spec.name

    async def ensure_markets(self) -> None:
        async with self._lock:
            if not self._markets_loaded:
                await self.exchange.load_markets()
                self._markets_loaded = True
                log.info("{}: loaded {} markets", self.name, len(self.exchange.markets))

    async def fetch_ohlcv(self, asset: str, timeframe: str = "1m", limit: int = 100, retries: int = 3) -> list[list]:
        """Return ``[[ts_ms, open, high, low, close, volume], ...]`` for ``asset``."""
        await self.ensure_markets()
        symbol = self.spec.symbol_for(asset)
        delay = 1.0
        for attempt in range(1, retries + 1):
            try:
                rows = await self.exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
                log.debug("{}: fetched {} x {} candles for {}", self.name, len(rows), timeframe, symbol)
                return rows
            except TRANSIENT_ERRORS as exc:
                if attempt == retries:
                    raise
                log.warning("{}: {} for {} (attempt {}/{}), retrying in {:.0f}s", self.name, type(exc).__name__, symbol, attempt, retries, delay)
                await asyncio.sleep(delay)
                delay *= 2
        return []  # unreachable

    async def fetch_ticker(self, asset: str) -> dict:
        await self.ensure_markets()
        return await self.exchange.fetch_ticker(self.spec.symbol_for(asset))

    async def close(self) -> None:
        await self.exchange.close()
