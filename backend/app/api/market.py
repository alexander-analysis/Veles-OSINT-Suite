"""/api/market/* - market intelligence endpoints.

Phase 1 ships ``GET /prices`` reading whatever candles exist (none until the
market bot lands in Phase 2).  Alerts, coordination, history and volatility
endpoints are added in Phase 2.
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.market import MarketCandle
from app.schemas.market import PriceQuote, PricesResponse
from app.utils.time import utcnow

router = APIRouter(tags=["market"])


def _csv(value: str | None) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()] if value else []


@router.get("/prices", response_model=PricesResponse, response_model_by_alias=True)
def get_prices(
    assets: str | None = Query(None, description="Comma-separated assets, e.g. BTC,ETH"),
    exchanges: str | None = Query(None, description="Comma-separated exchanges, e.g. binance,kraken"),
    db: Session = Depends(get_db),
) -> PricesResponse:
    """Latest known price per (asset, exchange), taken from the newest stored candle."""
    latest = (
        select(
            MarketCandle.asset,
            MarketCandle.exchange,
            func.max(MarketCandle.timestamp).label("timestamp"),
        )
        .group_by(MarketCandle.asset, MarketCandle.exchange)
        .subquery()
    )
    query = select(MarketCandle).join(
        latest,
        and_(
            MarketCandle.asset == latest.c.asset,
            MarketCandle.exchange == latest.c.exchange,
            MarketCandle.timestamp == latest.c.timestamp,
        ),
    )
    if wanted_assets := _csv(assets):
        query = query.where(MarketCandle.asset.in_([a.upper() for a in wanted_assets]))
    if wanted_exchanges := _csv(exchanges):
        query = query.where(MarketCandle.exchange.in_([e.lower() for e in wanted_exchanges]))

    candles = db.execute(query.order_by(MarketCandle.asset, MarketCandle.exchange)).scalars().all()
    return PricesResponse(
        timestamp=utcnow(),
        data=[
            PriceQuote(
                asset=candle.asset,
                exchange=candle.exchange,
                price=candle.close,
                timestamp=candle.timestamp,
                volume_24h_usd=candle.volume_usd,
            )
            for candle in candles
        ],
    )
