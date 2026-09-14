"""Kraken spot market data (public REST via ccxt).  USD-quoted pairs."""

from app.config import settings
from app.integrations.exchange_ccxt import ExchangeClient, ExchangeSpec

SPEC = ExchangeSpec(name="kraken", ccxt_id="kraken", quote="USD")


def create_client() -> ExchangeClient:
    return ExchangeClient(SPEC, api_key=settings.KRAKEN_API_KEY if settings.KRAKEN_API_KEY != "your_key_here" else "")
