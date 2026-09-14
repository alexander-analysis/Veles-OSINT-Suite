"""Market API schemas."""

from datetime import datetime

from pydantic import Field

from app.schemas.common import APIModel


class PriceQuote(APIModel):
    asset: str
    exchange: str
    price: float
    change_24h_percent: float | None = Field(None, alias="24h_change_percent")
    timestamp: datetime
    volume_24h_usd: float | None = None
    signal_quality: int | None = Field(None, description="0-100 confidence in the data source")


class PricesResponse(APIModel):
    timestamp: datetime
    data: list[PriceQuote]
