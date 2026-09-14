"""Price and volume anomaly detection.

* ``detect_price_anomalies`` - close deviates more than N sigma from the
  rolling baseline mean (default: 7 days of candles, 3 sigma).
* ``detect_volume_spikes``   - volume in the latest window (default 5 min) is
  more than N times the average window volume over the trailing 24 h.

Both return plain ``Anomaly`` records; persistence is the bot's job.
"""

from dataclasses import dataclass
from datetime import datetime

import numpy as np
import pandas as pd

from app.analysis.common import clamp, severity_for

PRICE_SEVERITY_SIGMA = (3.0, 4.0, 5.0, 7.0)  # low / medium / high / critical in sigma units
VOLUME_SEVERITY_MULTIPLIER = (2.0, 3.0, 5.0, 10.0)


@dataclass
class Anomaly:
    type: str  # price_anomaly | volume_spike
    exchange: str
    timestamp: datetime
    price: float
    change_percent: float | None
    severity: str
    confidence: float
    summary: str
    z_score: float | None = None
    volume: float | None = None
    volume_multiplier: float | None = None


def detect_price_anomalies(
    frame: pd.DataFrame,
    exchange: str,
    sigma: float = 3.0,
    baseline_points: int = 7 * 24 * 60,
    min_points: int = 60,
    evaluate_last: int = 10,
) -> list[Anomaly]:
    """Flag candles whose close is > ``sigma`` standard deviations from the rolling mean.

    The baseline for each candle excludes the candle itself (shifted window),
    so a spike cannot mask itself.  Only the last ``evaluate_last`` candles are
    evaluated - the caller runs this every few minutes and de-duplicates.
    """
    if len(frame) < min_points + 1:
        return []
    closes = frame["close"].astype(float)
    window = min(baseline_points, len(closes) - 1)
    rolling = closes.shift(1).rolling(window=window, min_periods=min_points)
    mean, std = rolling.mean(), rolling.std()
    z_scores = (closes - mean) / std.replace(0, np.nan)

    anomalies = []
    for timestamp, z in z_scores.tail(evaluate_last).items():
        if pd.isna(z) or abs(z) < sigma:
            continue
        severity = severity_for(abs(z), PRICE_SEVERITY_SIGMA)
        price = float(closes[timestamp])
        baseline = float(mean[timestamp])
        change_percent = (price - baseline) / baseline * 100 if baseline else None
        direction = "above" if z > 0 else "below"
        anomalies.append(
            Anomaly(
                type="price_anomaly",
                exchange=exchange,
                timestamp=timestamp.to_pydatetime(),
                price=price,
                change_percent=round(change_percent, 3) if change_percent is not None else None,
                z_score=round(float(z), 2),
                severity=severity,
                confidence=round(clamp(abs(z) / (2 * sigma)), 2),
                summary=f"{exchange}: close {price:,.2f} is {abs(z):.1f} sigma {direction} the {window}-candle mean ({baseline:,.2f})",
            )
        )
    return anomalies


def detect_volume_spikes(
    frame: pd.DataFrame,
    exchange: str,
    multiplier: float = 2.0,
    window_minutes: int = 5,
    baseline_hours: int = 24,
    min_windows: int = 12,
) -> list[Anomaly]:
    """Flag the latest ``window_minutes`` window if its volume is > ``multiplier`` x the trailing average window."""
    if frame.empty:
        return []
    volume = frame["volume"].astype(float)
    windows = volume.resample(f"{window_minutes}min").sum()
    windows = windows[windows.index <= frame.index[-1]]
    if len(windows) < min_windows + 1:
        return []
    latest_ts, latest = windows.index[-1], float(windows.iloc[-1])
    baseline_windows = windows.iloc[:-1].tail(max(1, baseline_hours * 60 // window_minutes))
    baseline = float(baseline_windows.mean())
    if baseline <= 0:
        return []
    ratio = latest / baseline
    if ratio < multiplier:
        return []
    closes = frame["close"].astype(float)
    window_closes = closes[closes.index >= latest_ts]
    price = float(window_closes.iloc[-1] if len(window_closes) else closes.iloc[-1])
    return [
        Anomaly(
            type="volume_spike",
            exchange=exchange,
            timestamp=latest_ts.to_pydatetime(),
            price=price,
            change_percent=None,
            volume=round(latest, 4),
            volume_multiplier=round(ratio, 2),
            severity=severity_for(ratio, VOLUME_SEVERITY_MULTIPLIER),
            confidence=round(clamp(0.5 + (ratio - multiplier) / (multiplier * 4)), 2),
            summary=f"{exchange}: {window_minutes}-minute volume {latest:,.2f} is {ratio:.1f}x the {baseline_hours}h average ({baseline:,.2f})",
        )
    ]
