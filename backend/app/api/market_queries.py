"""Query + pandas helpers behind the market endpoints (kept out of the router for readability)."""

from datetime import datetime, timedelta
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.analysis.common import candles_to_frame
from app.models.market import MarketCandle
from app.utils.time import to_iso_z, utcnow

RESAMPLE_RULES = {"1m": "1min", "5m": "5min", "15m": "15min", "1h": "1h", "4h": "4h", "1d": "1D"}
OHLCV_AGG = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}


def signal_quality(timestamp: datetime) -> int:
    """0-100: how fresh the latest candle is (100 = under 2 min old, 0 = older than an hour)."""
    age = (utcnow() - timestamp).total_seconds()
    return int(max(0, min(100, 100 - (age - 120) / 34)))


def change_and_volume_24h(db: Session, latest: MarketCandle) -> tuple[float | None, float | None]:
    """24h % change (vs the candle closest to 24h ago) and summed USD volume over 24h."""
    since = latest.timestamp - timedelta(hours=24)
    reference = db.execute(
        select(MarketCandle.close)
        .where(
            MarketCandle.asset == latest.asset,
            MarketCandle.exchange == latest.exchange,
            MarketCandle.timeframe == latest.timeframe,
            MarketCandle.timestamp <= since,
        )
        .order_by(MarketCandle.timestamp.desc())
        .limit(1)
    ).scalar()
    volume = db.execute(
        select(func.sum(MarketCandle.volume_usd)).where(
            MarketCandle.asset == latest.asset,
            MarketCandle.exchange == latest.exchange,
            MarketCandle.timeframe == latest.timeframe,
            MarketCandle.timestamp > since,
        )
    ).scalar()
    change = round((latest.close - reference) / reference * 100, 3) if reference else None
    return change, round(float(volume), 2) if volume else None


def _frames_for(db: Session, asset: str, start: datetime, end: datetime, exchanges: list[str]) -> dict[str, pd.DataFrame]:
    query = select(MarketCandle).where(MarketCandle.asset == asset, MarketCandle.timestamp.between(start, end))
    if exchanges:
        query = query.where(MarketCandle.exchange.in_(exchanges))
    rows = db.execute(query.order_by(MarketCandle.timestamp)).scalars().all()
    by_exchange: dict[str, list] = {}
    for row in rows:
        by_exchange.setdefault(row.exchange, []).append(row)
    return {name: candles_to_frame(items) for name, items in by_exchange.items()}


def history_candles(
    db: Session, asset: str, start: datetime, end: datetime, timeframe: str, exchanges: list[str]
) -> tuple[list[dict[str, Any]], list[str]]:
    frames = _frames_for(db, asset, start, end, exchanges)
    if not frames:
        return [], []
    rule = RESAMPLE_RULES[timeframe]
    resampled = {}
    for name, frame in frames.items():
        if timeframe != "1m":
            frame = frame.resample(rule, label="left", closed="left").agg(OHLCV_AGG).dropna(subset=["close"])
        resampled[name] = frame
    index = sorted(set().union(*(set(f.index) for f in resampled.values())))
    candles = []
    for ts in index:
        row: dict[str, Any] = {"timestamp": to_iso_z(ts.to_pydatetime())}
        closes, volumes = [], []
        for name, frame in resampled.items():
            if ts in frame.index:
                bar = frame.loc[ts]
                row[name] = {k: round(float(bar[k]), 8) for k in ("open", "high", "low", "close", "volume")}
                closes.append(float(bar["close"]))
                volumes.append(float(bar["volume"]))
        row["composite"] = {"close": round(float(np.mean(closes)), 8), "volume_total": round(float(np.sum(volumes)), 8)}
        candles.append(row)
    return candles, sorted(resampled)


def volatility(
    db: Session, asset: str, hours: int, window_minutes: int, cluster_multiplier: float, extreme_move_percent: float
) -> dict[str, Any]:
    end = utcnow()
    frames = _frames_for(db, asset, end - timedelta(hours=hours), end, [])
    exchanges: dict[str, dict[str, Any]] = {}
    series: dict[datetime, dict[str, Any]] = {}
    clusters: list[dict[str, Any]] = []
    rule = f"{window_minutes}min"

    for name, frame in frames.items():
        closes = frame["close"].astype(float)
        returns = closes.pct_change().dropna() * 100
        if len(returns) < 5:
            continue
        candles_per_day = 1440 if (closes.index[1] - closes.index[0]) <= timedelta(minutes=1) else 288
        realized_daily = float(returns.std() * np.sqrt(candles_per_day))
        windows = closes.resample(rule).agg(["first", "last"]).dropna()
        moves = ((windows["last"] - windows["first"]) / windows["first"] * 100).abs()
        window_vol = returns.resample(rule).std().dropna()
        baseline = float(window_vol.median()) if len(window_vol) else 0.0
        exchanges[name] = {
            "candles": int(len(closes)),
            "realized_volatility_daily_percent": round(realized_daily, 4),
            "realized_volatility_annualized_percent": round(realized_daily * np.sqrt(365), 2),
            "max_window_move_percent": round(float(moves.max()), 4) if len(moves) else None,
            "mean_abs_return_percent": round(float(returns.abs().mean()), 5),
            "extreme_windows": int((moves >= extreme_move_percent).sum()),
        }
        for ts, value in window_vol.items():
            series.setdefault(ts.to_pydatetime(), {"timestamp": to_iso_z(ts.to_pydatetime())})[name] = round(float(value), 5)
        # cluster = consecutive windows whose volatility exceeds cluster_multiplier x the median
        active = window_vol > baseline * cluster_multiplier if baseline > 0 else window_vol > 0
        start = None
        for ts, flag in active.items():
            if flag and start is None:
                start = ts
            elif not flag and start is not None:
                clusters.append(_cluster(name, start, ts, window_vol, baseline))
                start = None
        if start is not None:
            clusters.append(_cluster(name, start, window_vol.index[-1] + timedelta(minutes=window_minutes), window_vol, baseline))

    return {
        "exchanges": exchanges,
        "clusters": sorted(clusters, key=lambda c: c["start"], reverse=True),
        "series": [series[key] for key in sorted(series)],
    }


def _cluster(exchange: str, start, end, window_vol: pd.Series, baseline: float) -> dict[str, Any]:
    segment = window_vol[(window_vol.index >= start) & (window_vol.index < end)]
    peak = float(segment.max()) if len(segment) else 0.0
    return {
        "exchange": exchange,
        "start": to_iso_z(start.to_pydatetime()),
        "end": to_iso_z(end.to_pydatetime()),
        "windows": int(len(segment)),
        "peak_volatility_percent": round(peak, 5),
        "multiple_of_median": round(peak / baseline, 2) if baseline else None,
    }
