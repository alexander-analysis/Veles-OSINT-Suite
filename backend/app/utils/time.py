"""Time helpers.

Every timestamp stored by VELES is a *naive* UTC ``datetime`` - SQLite has no
timezone type, and mixing aware/naive values makes comparisons blow up.  API
responses render them with a trailing ``Z`` so clients know they are UTC.
"""

from datetime import datetime, timezone


def utcnow() -> datetime:
    """Current UTC time as a naive datetime (replacement for deprecated ``utcnow``)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def from_unix_ms(milliseconds: int | float) -> datetime:
    """Convert an epoch timestamp in milliseconds (ccxt convention) to naive UTC."""
    return datetime.fromtimestamp(milliseconds / 1000, tz=timezone.utc).replace(tzinfo=None)


def from_unix_seconds(seconds: int | float) -> datetime:
    """Convert an epoch timestamp in seconds (AIS convention) to naive UTC."""
    return datetime.fromtimestamp(seconds, tz=timezone.utc).replace(tzinfo=None)


def to_unix_ms(value: datetime) -> int:
    """Naive-UTC datetime -> epoch milliseconds (``value.timestamp()`` would assume *local* time)."""
    return int(value.replace(tzinfo=timezone.utc).timestamp() * 1000)


def to_iso_z(value: datetime | None) -> str | None:
    """Render a naive-UTC datetime as ISO-8601 with a ``Z`` suffix."""
    if value is None:
        return None
    return value.replace(microsecond=0).isoformat() + "Z"
