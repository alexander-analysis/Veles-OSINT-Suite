"""Helpers shared by the market analysis modules."""

from collections.abc import Iterable

import pandas as pd

CANDLE_COLUMNS = ["open", "high", "low", "close", "volume"]


def candles_to_frame(candles: Iterable) -> pd.DataFrame:
    """Turn candle rows (ORM objects or dicts) into a time-indexed DataFrame.

    Duplicate timestamps keep the last value; the index is sorted.
    """
    records = []
    for candle in candles:
        get = candle.get if isinstance(candle, dict) else lambda key, c=candle: getattr(c, key)
        records.append({"timestamp": get("timestamp"), **{column: float(get(column)) for column in CANDLE_COLUMNS}})
    if not records:
        return pd.DataFrame(columns=CANDLE_COLUMNS, index=pd.DatetimeIndex([], name="timestamp"))
    frame = pd.DataFrame.from_records(records).drop_duplicates("timestamp", keep="last")
    frame["timestamp"] = pd.to_datetime(frame["timestamp"])
    return frame.set_index("timestamp").sort_index()


def severity_for(value: float, thresholds: tuple[float, float, float, float]) -> str:
    """Map a magnitude onto low/medium/high/critical using ascending thresholds."""
    low, medium, high, critical = thresholds
    if value >= critical:
        return "critical"
    if value >= high:
        return "high"
    if value >= medium:
        return "medium"
    return "low" if value >= low else "none"


def clamp(value: float, lower: float = 0.0, upper: float = 0.99) -> float:
    return max(lower, min(upper, value))
