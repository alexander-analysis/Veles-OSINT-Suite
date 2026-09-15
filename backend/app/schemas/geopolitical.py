"""Geopolitical event monitor API schemas."""

from datetime import datetime
from typing import Any

from pydantic import Field

from app.schemas.common import APIModel


class EventCorrelationOut(APIModel):
    id: int
    geopolitical_event_id: int
    alert_type: str
    alert_id: int
    alert_timestamp: datetime
    alert_summary: str | None = None
    time_delta_minutes: int | None = None
    time_delta_direction: str | None = None
    correlation_score: float | None = None
    correlation_type: str | None = None
    intelligence_analysis: str | None = None
    detected_at: datetime


class GeopoliticalEventOut(APIModel):
    id: int
    event_type: str
    title: str
    description: str | None = None
    country_primary: str | None = None
    country_secondary: str | None = None
    region: str | None = None
    coordinates_lat: float | None = None
    coordinates_lon: float | None = None
    event_date: datetime
    detected_date: datetime
    severity: str | None = None
    source: str | None = None
    source_id: str | None = None
    source_urls: list[str] | None = None
    verification_status: str | None = None
    confidence_score: float | None = None
    keywords: list[str] | None = None
    affected_sectors: list[str] | None = None
    affected_countries: list[str] | None = None
    goldstein_scale: float | None = None
    mentions: int | None = None
    correlated_with_market: bool = False
    correlated_with_maritime: bool = False
    correlated_with_sanctions: bool = False
    market_impact: str | None = None
    supply_chain_impact: str | None = None
    intelligence_notes: str | None = None


class GeopoliticalEventDetail(GeopoliticalEventOut):
    correlations: list[EventCorrelationOut] = Field(default_factory=list)


class EventsResponse(APIModel):
    total: int
    limit: int
    offset: int
    filters: dict[str, Any]
    events: list[GeopoliticalEventOut]


class CorrelationsResponse(APIModel):
    hours: int
    total: int
    correlations: list[EventCorrelationOut]


class TimelineBucket(APIModel):
    day: datetime
    total: int
    by_type: dict[str, int]
    max_severity: str | None = None


class TimelineResponse(APIModel):
    country: str
    days: int
    total: int
    buckets: list[TimelineBucket]
    events: list[GeopoliticalEventOut]


class NewsSourceOut(APIModel):
    id: int
    source_name: str
    source_url: str | None = None
    source_type: str | None = None
    categories: list[str] | None = None
    enabled: bool
    last_fetch: datetime | None = None
    last_status: str | None = None
    items_total: int | None = None
    reliability_score: float | None = None
    latency_seconds: int | None = None


class VerifyRequest(APIModel):
    status: str = Field(pattern="^(unconfirmed|confirmed|disputed)$")
    notes: str | None = Field(None, max_length=1000)
    analyst: str | None = Field(None, max_length=100)
