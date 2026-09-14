"""JSON helpers for endpoints that return plain dicts (not Pydantic models)."""

from datetime import datetime
from typing import Any

from app.utils.time import to_iso_z


def jsonable(value: Any) -> Any:
    """Recursively convert naive-UTC datetimes to ISO-8601 ``Z`` strings."""
    if isinstance(value, datetime):
        return to_iso_z(value)
    if isinstance(value, dict):
        return {k: jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    return value
