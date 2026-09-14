"""Market API schemas."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.common import APIModel

Severity = Literal["low", "medium", "high", "critical"]
InvestigationStatus = Literal["flagged", "investigating", "cleared", "escalated"]


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


class AlertOut(APIModel):
    id: int
    asset: str
    alert_type: str
    severity: str
    exchanges_involved: list[str] | None = None
    price_at_alert: float
    price_change_percent: float | None = None
    volume: float | None = None
    volume_multiplier: float | None = None
    confidence_score: float | None = None
    timestamp: datetime
    detected_at: datetime
    acknowledged: bool
    acknowledged_by: str | None = None
    acknowledged_at: datetime | None = None
    notes: str | None = None
    intelligence_summary: str | None = Field(None, validation_alias="summary")


class AlertsResponse(APIModel):
    total: int
    limit: int
    offset: int
    alerts: list[AlertOut]


class AcknowledgeRequest(BaseModel):
    acknowledged_by: str = Field("anonymous", max_length=100)
    notes: str | None = Field(None, max_length=500)


class CoordinationOut(APIModel):
    id: int
    asset: str
    exchanges: list[str]
    time_delta_seconds: int | None = None
    correlated_price_move: float | None = None
    volume_coordination: float | None = None
    confidence_score: float | None = None
    detected_at: datetime
    investigation_status: str | None = None
    analyst_notes: str | None = None
    analyst_assessment: str | None = Field(None, validation_alias="summary")


class CoordinationResponse(APIModel):
    total: int
    events: list[CoordinationOut]


class CoordinationUpdate(BaseModel):
    investigation_status: InvestigationStatus | None = None
    analyst_notes: str | None = Field(None, max_length=500)
    updated_by: str = Field("anonymous", max_length=100)


class HistoryResponse(APIModel):
    asset: str
    timeframe: str
    period: str
    exchanges: list[str]
    candles: list[dict[str, Any]]
    anomalies_in_period: list[dict[str, Any]]


class VolatilityResponse(APIModel):
    asset: str
    hours: int
    window_minutes: int
    exchanges: dict[str, dict[str, Any]]
    clusters: list[dict[str, Any]]
    series: list[dict[str, Any]]


class BotStatus(APIModel):
    last_fetch_at: datetime | None = None
    last_fetch_counts: dict[str, int] = {}
    candles_stored: int = 0
    open_alerts: int = 0
    liquidation_stream: dict[str, Any] = {}
