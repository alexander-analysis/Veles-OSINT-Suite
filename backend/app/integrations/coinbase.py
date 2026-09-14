"""Coinbase (Advanced Trade) market data via ccxt.  USD-quoted pairs, public candles."""

from app.config import settings
from app.integrations.exchange_ccxt import ExchangeClient, ExchangeSpec

SPEC = ExchangeSpec(name="coinbase", ccxt_id="coinbase", quote="USD")


def create_client() -> ExchangeClient:
    return ExchangeClient(SPEC, api_key=settings.COINBASE_API_KEY if settings.COINBASE_API_KEY != "your_key_here" else "")
