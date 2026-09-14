"""Market-intelligence tables: candles, anomaly alerts, coordination and liquidation events."""

from sqlalchemy import JSON, Boolean, Column, DateTime, Float, Index, Integer, String, UniqueConstraint

from app.models.base import Base, TimestampMixin, utcnow


class MarketCandle(TimestampMixin, Base):
    """Raw OHLCV candle data from exchanges."""

    __tablename__ = "market_candles"

    id = Column(Integer, primary_key=True)
    asset = Column(String(50), nullable=False, index=True)  # BTC, ETH, GOLD, OIL, ...
    exchange = Column(String(50), nullable=False, index=True)  # binance, kraken, coinbase, yfinance
    timeframe = Column(String(10), nullable=False)  # 1m, 5m, 15m, 1h
    timestamp = Column(DateTime, nullable=False, index=True)  # UTC time of candle open
    open = Column(Float, nullable=False)
    high = Column(Float, nullable=False)
    low = Column(Float, nullable=False)
    close = Column(Float, nullable=False)
    volume = Column(Float, nullable=False)
    volume_usd = Column(Float)  # USD-equivalent volume

    __table_args__ = (
        Index("ix_market_candles_asset_exchange_timestamp", "asset", "exchange", "timestamp"),
        # The fetcher re-reads the last N candles every minute; this lets it
        # upsert instead of piling up duplicates.
        UniqueConstraint(
            "asset", "exchange", "timeframe", "timestamp", name="uq_market_candles_asset_exchange_timeframe_ts"
        ),
    )


class MarketAlert(Base):
    """Detected anomalies: price spikes, volume anomalies, coordination, liquidation."""

    __tablename__ = "market_alerts"

    id = Column(Integer, primary_key=True)
    asset = Column(String(50), nullable=False, index=True)
    alert_type = Column(String(50), nullable=False)  # price_anomaly, volume_spike, coordination, liquidation
    severity = Column(String(20), nullable=False, index=True)  # low, medium, high, critical
    exchanges_involved = Column(JSON)  # list of exchanges affected
    price_at_alert = Column(Float, nullable=False)
    price_change_percent = Column(Float)  # % change from baseline
    volume = Column(Float)  # absolute volume
    volume_multiplier = Column(Float)  # vs 24h average
    timestamp = Column(DateTime, nullable=False, index=True)  # when the anomaly occurred
    detected_at = Column(DateTime, default=utcnow, nullable=False)
    acknowledged = Column(Boolean, default=False, nullable=False)
    acknowledged_by = Column(String(100))  # username if multi-user
    acknowledged_at = Column(DateTime)
    notes = Column(String(500))  # analyst notes
    confidence_score = Column(Float)  # 0.0-1.0

    __table_args__ = (Index("ix_market_alerts_asset_timestamp", "asset", "timestamp"),)


class CoordinationEvent(Base):
    """Cross-exchange trading coordination detected."""

    __tablename__ = "coordination_events"

    id = Column(Integer, primary_key=True)
    asset = Column(String(50), nullable=False, index=True)
    exchanges = Column(JSON, nullable=False)  # ["binance", "kraken", "coinbase"]
    time_delta_seconds = Column(Integer)  # window between the correlated moves
    correlated_price_move = Column(Float)  # % movement coordinated
    volume_coordination = Column(Float)  # volume spike coordination
    confidence_score = Column(Float)  # 0.0-1.0 (higher = more suspicious)
    detected_at = Column(DateTime, nullable=False, index=True, default=utcnow)
    investigation_status = Column(String(50), default="flagged")  # flagged, investigating, cleared, escalated
    analyst_notes = Column(String(500))

    __table_args__ = (Index("ix_coordination_events_asset_detected", "asset", "detected_at"),)


class LiquidationCascade(Base):
    """Tracked futures liquidation events."""

    __tablename__ = "liquidation_cascades"

    id = Column(Integer, primary_key=True)
    asset = Column(String(50), nullable=False, index=True)
    exchange = Column(String(50), nullable=False)
    initial_liquidation_usd = Column(Float)
    cascade_liquidations = Column(Integer)  # count of secondary liquidations
    total_liquidated_usd = Column(Float)
    price_impact = Column(Float)  # % price moved due to liquidations
    trigger_source = Column(String(200))  # what caused the initial liquidation
    timestamp = Column(DateTime, nullable=False, index=True)
    detected_at = Column(DateTime, default=utcnow, nullable=False)
    correlation_score = Column(Float)  # correlation to an external event
    external_event = Column(String(300))  # sanctions announcement, geopolitical event, ...
