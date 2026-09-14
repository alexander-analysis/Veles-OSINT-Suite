"""Shared model plumbing: the declarative base and common column mixins."""

from sqlalchemy import Column, DateTime

from app.database import Base
from app.utils.time import utcnow


class TimestampMixin:
    """``created_at`` set when the row is inserted (naive UTC)."""

    created_at = Column(DateTime, default=utcnow, nullable=False)


class UpdatedTimestampMixin(TimestampMixin):
    """``created_at`` plus ``updated_at`` refreshed on every UPDATE."""

    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)


__all__ = ["Base", "TimestampMixin", "UpdatedTimestampMixin", "utcnow"]
