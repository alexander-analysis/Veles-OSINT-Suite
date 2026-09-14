"""Unit tests for the market analysis modules on synthetic candles."""

from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from app.analysis.common import candles_to_frame
from app.analysis.coordination import detect_cross_exchange_coordination
from app.analysis.liquidation import correlate_with_events, detect_cascades
from app.analysis.market_anomaly import detect_price_anomalies, detect_volume_spikes

T0 = datetime(2026, 9, 1, 0, 0)


def make_frame(n: int = 600, price: float = 100.0, noise: float = 0.05, volume: float = 10.0, seed: int = 1) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    closes = price + rng.normal(0, noise, n).cumsum() * 0.1
    rows = [
        {"timestamp": T0 + timedelta(minutes=i), "open": c, "high": c + 0.01, "low": c - 0.01, "close": c, "volume": volume + rng.normal(0, 0.5)}
        for i, c in enumerate(closes)
    ]
    return candles_to_frame(rows)


def test_candles_to_frame_dedupes_and_sorts():
    rows = [
        {"timestamp": T0 + timedelta(minutes=1), "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1},
        {"timestamp": T0, "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1},
        {"timestamp": T0 + timedelta(minutes=1), "open": 2, "high": 2, "low": 2, "close": 2, "volume": 2},
    ]
    frame = candles_to_frame(rows)
    assert list(frame.index) == [pd.Timestamp(T0), pd.Timestamp(T0 + timedelta(minutes=1))]
    assert frame["close"].iloc[-1] == 2


def test_price_anomaly_fires_on_spike_and_is_quiet_otherwise():
    frame = make_frame()
    assert detect_price_anomalies(frame, "binance", sigma=3.0) == []

    spiked = frame.copy()
    spiked.iloc[-1, spiked.columns.get_loc("close")] = frame["close"].iloc[-1] * 1.5
    anomalies = detect_price_anomalies(spiked, "binance", sigma=3.0)
    assert len(anomalies) == 1
    anomaly = anomalies[0]
    assert anomaly.type == "price_anomaly"
    assert anomaly.severity == "critical"
    assert anomaly.z_score > 7
    assert anomaly.change_percent > 40
    assert 0.5 <= anomaly.confidence <= 0.99
    assert anomaly.timestamp == spiked.index[-1].to_pydatetime()


def test_price_anomaly_needs_enough_history():
    assert detect_price_anomalies(make_frame(n=30), "kraken") == []


def test_volume_spike_detection():
    frame = make_frame(n=24 * 60 + 10)
    assert detect_volume_spikes(frame, "binance", multiplier=2.0) == []

    spiked = frame.copy()
    spiked.iloc[-5:, spiked.columns.get_loc("volume")] = 60.0  # 5-minute window ~6x baseline
    spikes = detect_volume_spikes(spiked, "binance", multiplier=2.0)
    assert len(spikes) == 1
    assert spikes[0].type == "volume_spike"
    assert spikes[0].volume_multiplier > 4
    assert spikes[0].severity in {"high", "critical"}


def test_coordination_detects_synchronised_move():
    base = make_frame(n=120, noise=0.02)
    frames = {}
    for i, name in enumerate(["binance", "kraken", "coinbase"]):
        frame = base.copy()
        frame["close"] = frame["close"] + i * 0.001  # nearly identical price series -> high correlation
        frames[name] = frame
    assert detect_cross_exchange_coordination("BTC", frames, min_move_percent=2.0) == []

    for frame in frames.values():
        frame.iloc[-2, frame.columns.get_loc("close")] *= 1.03  # +3% on all venues in the same minute
        frame.iloc[-1, frame.columns.get_loc("close")] = frame["close"].iloc[-2]
    events = detect_cross_exchange_coordination("BTC", frames, min_move_percent=2.0, min_correlation=0.85)
    assert len(events) == 1
    event = events[0]
    assert event.exchanges == ["binance", "coinbase", "kraken"]
    assert event.time_delta_seconds == 0
    assert event.move_percent > 2.5
    assert event.correlation >= 0.85
    assert event.price > 0
    assert "Synchronised" in event.summary


def test_coordination_ignores_single_exchange_move():
    frames = {name: make_frame(n=120, noise=0.02, seed=i) for i, name in enumerate(["binance", "kraken"])}
    frames["binance"].iloc[-1, frames["binance"].columns.get_loc("close")] *= 1.05
    assert detect_cross_exchange_coordination("BTC", frames) == []


def test_liquidation_cascades_and_correlation():
    events = [
        {"asset": "BTC", "exchange": "binance", "side": "sell", "price": 100 - i * 0.5, "quantity": 5000, "usd": 500_000, "timestamp": T0 + timedelta(seconds=20 * i)}
        for i in range(8)
    ]
    events.append({"asset": "BTC", "exchange": "binance", "side": "buy", "price": 99, "quantity": 1, "usd": 99, "timestamp": T0 + timedelta(hours=2)})
    events.append({"asset": "ETH", "exchange": "binance", "side": "sell", "price": 10, "quantity": 1, "usd": 10, "timestamp": T0})
    cascades = detect_cascades(events, gap_minutes=2, min_events=5, min_total_usd=1_000_000)
    assert len(cascades) == 1
    cascade = cascades[0]
    assert cascade.asset == "BTC" and cascade.count == 8
    assert cascade.total_usd == 4_000_000
    assert cascade.dominant_side == "sell"
    assert cascade.price_impact_percent < 0

    correlate_with_events(cascade, [(T0 + timedelta(minutes=5), "BTC price anomaly")], window_minutes=15)
    assert cascade.correlated_event == "BTC price anomaly"
    assert 0 < cascade.correlation_score <= 1
