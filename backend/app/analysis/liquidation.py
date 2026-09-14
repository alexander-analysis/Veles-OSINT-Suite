"""Futures liquidation cascade detection.

A cascade is a burst of liquidations for one asset on one exchange: at least
``min_events`` orders with no gap longer than ``gap_minutes`` between
consecutive ones, and a total notional above ``min_total_usd``.  Cascades
are then correlated with other timestamped events (price anomalies, sanctions
list updates, ...) that fall inside a window around them.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta


@dataclass
class Cascade:
    asset: str
    exchange: str
    start: datetime
    end: datetime
    count: int
    initial_usd: float
    total_usd: float
    price_impact_percent: float | None
    dominant_side: str  # sell = longs liquidated, buy = shorts liquidated
    summary: str
    correlated_event: str | None = None
    correlation_score: float | None = None
    events: list = field(default_factory=list, repr=False)


def detect_cascades(
    events: list[dict],
    gap_minutes: float = 2.0,
    min_events: int = 5,
    min_total_usd: float = 1_000_000,
) -> list[Cascade]:
    """Cluster liquidation events into cascades."""
    by_key: dict[tuple[str, str], list[dict]] = {}
    for event in events:
        by_key.setdefault((event["asset"], event["exchange"]), []).append(event)

    cascades: list[Cascade] = []
    gap = timedelta(minutes=gap_minutes)
    for (asset, exchange), items in by_key.items():
        items.sort(key=lambda e: e["timestamp"])
        cluster: list[dict] = []
        for event in items + [None]:
            if event is not None and (not cluster or event["timestamp"] - cluster[-1]["timestamp"] <= gap):
                cluster.append(event)
                continue
            if cluster:
                cascade = _summarise(asset, exchange, cluster)
                if cascade.count >= min_events and cascade.total_usd >= min_total_usd:
                    cascades.append(cascade)
            cluster = [event] if event is not None else []
    return cascades


def _summarise(asset: str, exchange: str, cluster: list[dict]) -> Cascade:
    total = sum(e["usd"] for e in cluster)
    first_price, last_price = cluster[0]["price"], cluster[-1]["price"]
    impact = (last_price - first_price) / first_price * 100 if first_price else None
    sells = sum(e["usd"] for e in cluster if e.get("side") == "sell")
    side = "sell" if sells >= total / 2 else "buy"
    minutes = (cluster[-1]["timestamp"] - cluster[0]["timestamp"]).total_seconds() / 60
    return Cascade(
        asset=asset,
        exchange=exchange,
        start=cluster[0]["timestamp"],
        end=cluster[-1]["timestamp"],
        count=len(cluster),
        initial_usd=cluster[0]["usd"],
        total_usd=total,
        price_impact_percent=round(impact, 3) if impact is not None else None,
        dominant_side=side,
        summary=(
            f"{len(cluster)} {asset} liquidations on {exchange} in {minutes:.1f} min "
            f"totalling ${total:,.0f} ({'longs' if side == 'sell' else 'shorts'} flushed)"
        ),
        events=cluster,
    )


def correlate_with_events(cascade: Cascade, external: list[tuple[datetime, str]], window_minutes: int = 15) -> Cascade:
    """Attach the closest external event inside +/- ``window_minutes`` and score the overlap."""
    best: tuple[float, str] | None = None
    for timestamp, description in external:
        distance = min(abs((timestamp - cascade.start).total_seconds()), abs((timestamp - cascade.end).total_seconds())) / 60
        if distance <= window_minutes and (best is None or distance < best[0]):
            best = (distance, description)
    if best:
        cascade.correlated_event = best[1]
        cascade.correlation_score = round(1 - best[0] / window_minutes, 2)
    return cascade
