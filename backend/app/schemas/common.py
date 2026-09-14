"""Schemas shared across routers: base model, health, pagination."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from app.utils.time import to_iso_z


class APIModel(BaseModel):
    """Base for all response models: ORM-friendly, datetimes rendered as ISO-8601 ``Z``."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    @field_serializer("*", mode="wrap", when_used="json", check_fields=False)
    def _serialize_datetimes(self, value: Any, handler):
        # Naive datetimes would otherwise render without a timezone marker and
        # be parsed as *local* time by browsers.
        return to_iso_z(value) if isinstance(value, datetime) else handler(value)


class Pagination(APIModel):
    total: int
    limit: int
    offset: int


class DatabaseHealth(APIModel):
    ok: bool
    dialect: str
    size_bytes: int | None = Field(None, description="Size of the SQLite file (+WAL) if applicable")
    error: str | None = None


class SchedulerJob(APIModel):
    id: str
    next_run_time: datetime | None = None


class SchedulerHealth(APIModel):
    enabled: bool
    running: bool
    jobs: list[SchedulerJob] = []


class HealthResponse(APIModel):
    status: str = Field(description='"ok" or "degraded"')
    version: str
    environment: str
    timestamp: datetime
    uptime_seconds: float
    database: DatabaseHealth
    scheduler: SchedulerHealth
    last_market_update: datetime | None = Field(None, description="Newest market candle timestamp")
    last_ais_update: datetime | None = Field(None, description="Newest vessel position timestamp")
