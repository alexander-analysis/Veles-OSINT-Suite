"""Cross-exchange coordination detection.

Looks for the same asset moving sharply on two or more exchanges inside a
short window *and* those exchanges' recent returns being highly correlated.
A large synchronised move with correlation > 0.85 is the brief's signature
for coordinated activity (pump groups, wash-trading across venues).

Candles are 1-minute, so "within 30 seconds" resolves to the same candle
(``time_delta_seconds = 0``); adjacent candles are also accepted and reported
as 60 s so slightly skewed exchange clocks do not hide an event.
"""

from dataclasses import dataclass
from datetime import datetime
from itertools import combinations

import pandas as pd

from app.analysis.common import clamp


@dataclass
class Coordination:
    asset: str
    exchanges: list[str]
    timestamp: datetime
    time_delta_seconds: int
    move_percent: float  # mean absolute move across the exchanges involved
    correlation: float  # min pairwise correlation of recent returns
    volume_coordination: float | None  # mean volume multiplier vs trailing average
    price: float  # close on the first exchange at the event candle
    confidence: float
    summary: str


def _returns(frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    closes = pd.concat({name: frame["close"].astype(float) for name, frame in frames.items()}, axis=1)
    closes = closes.dropna(how="any")
    return closes.pct_change().dropna(how="any") * 100


def detect_cross_exchange_coordination(
    asset: str,
    frames_by_exchange: dict[str, pd.DataFrame],
    window_seconds: int = 30,
    min_correlation: float = 0.85,
    min_move_percent: float = 2.0,
    lookback_minutes: int = 60,
    evaluate_last: int = 10,
) -> list[Coordination]:
    frames = {name: frame for name, frame in frames_by_exchange.items() if len(frame) >= 3}
    if len(frames) < 2:
        return []
    returns = _returns(frames)
    if len(returns) < 5:
        return []
    candle_seconds = 60
    neighbour = 1 if window_seconds > 0 else 0  # adjacent-candle tolerance

    events: list[Coordination] = []
    seen: set[datetime] = set()
    for timestamp in returns.tail(evaluate_last).index:
        position = returns.index.get_loc(timestamp)
        window = returns.iloc[max(0, position - neighbour) : position + neighbour + 1]
        movers = {}
        for exchange in returns.columns:
            column = window[exchange]
            idx = column.abs().idxmax()
            if abs(column[idx]) >= min_move_percent:
                movers[exchange] = (idx, float(column[idx]))
        if len(movers) < 2:
            continue
        # direction must agree (all up or all down) for a coordinated move
        signs = {move > 0 for _, move in movers.values()}
        if len(signs) != 1:
            continue
        history = returns.iloc[max(0, position - lookback_minutes) : position + 1]
        correlations = []
        for a, b in combinations(movers, 2):
            corr = history[a].corr(history[b])
            correlations.append(float(corr) if pd.notna(corr) else 0.0)
        correlation = min(correlations)
        if correlation < min_correlation:
            continue
        stamps = sorted(idx for idx, _ in movers.values())
        time_delta = int((stamps[-1] - stamps[0]).total_seconds())
        if time_delta > candle_seconds * neighbour:
            continue
        event_time = stamps[0].to_pydatetime()
        if event_time in seen:
            continue
        seen.add(event_time)

        move = sum(abs(m) for _, m in movers.values()) / len(movers)
        first_exchange = sorted(movers)[0]
        price = float(frames[first_exchange]["close"].asof(stamps[0]))
        volume_multipliers = []
        for exchange in movers:
            volumes = frames[exchange]["volume"].astype(float)
            trailing = volumes[volumes.index < stamps[0]].tail(lookback_minutes)
            if len(trailing) and trailing.mean() > 0 and stamps[0] in volumes.index:
                volume_multipliers.append(float(volumes[stamps[0]] / trailing.mean()))
        volume_coordination = round(sum(volume_multipliers) / len(volume_multipliers), 2) if volume_multipliers else None

        confidence = clamp(
            0.4
            + 0.3 * (correlation - min_correlation) / max(1e-9, 1 - min_correlation)
            + 0.3 * min(1.0, (move - min_move_percent) / max(min_move_percent, 1e-9))
        )
        direction = "up" if signs == {True} else "down"
        events.append(
            Coordination(
                asset=asset,
                exchanges=sorted(movers),
                timestamp=event_time,
                time_delta_seconds=time_delta,
                move_percent=round(move, 3),
                correlation=round(correlation, 3),
                volume_coordination=volume_coordination,
                price=price,
                confidence=round(confidence, 2),
                summary=(
                    f"Synchronised {move:.2f}% move {direction} on {', '.join(sorted(movers))} within {time_delta}s "
                    f"(return correlation {correlation:.2f} over {lookback_minutes} min)"
                ),
            )
        )
    return events
