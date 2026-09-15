"""Market intelligence bot.

Jobs (scheduled in ``app.bots.scheduler``, run on the bot event loop):

* ``fetch_candles_all_exchanges`` - 1m OHLCV for every monitored asset on every
  exchange, upserted into ``market_candles``.
* ``fetch_commodities``           - yfinance 5m candles for configured tickers.
* ``analyze_anomalies``           - 3-sigma price deviations and volume spikes.
* ``analyze_coordination``        - synchronised cross-exchange moves.
* ``analyze_liquidations``        - futures liquidation cascades.
* ``cleanup_old_data``            - retention purge of old candles.

Thresholds and asset lists are re-read from the config store on every run so
``POST /api/admin/config`` takes effect without a restart.
"""

import asyncio
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app import notifications
from app.analysis.common import candles_to_frame
from app.analysis.coordination import Coordination, detect_cross_exchange_coordination
from app.analysis.liquidation import correlate_with_events, detect_cascades
from app.analysis.market_anomaly import Anomaly, detect_price_anomalies, detect_volume_spikes
from app.database import SessionLocal
from app.integrations import binance, coinbase, kraken
from app.integrations import yfinance as commodities
from app.integrations.exchange_ccxt import ExchangeClient
from app.models.audit import AuditLog
from app.models.market import CoordinationEvent, LiquidationCascade, MarketAlert, MarketCandle
from app.models.audit import DataRetentionPolicy
from app.utils import config_store
from app.utils.logger import logger
from app.utils.time import from_unix_ms, utcnow

log = logger.bind(component="market")

EXCHANGE_FACTORIES = {"binance": binance.create_client, "kraken": kraken.create_client, "coinbase": coinbase.create_client}
LIQUIDATION_SEVERITY_USD = (1_000_000, 5_000_000, 20_000_000, 100_000_000)


class MarketBot:
    def __init__(self) -> None:
        self.clients: dict[str, ExchangeClient] = {}
        self.liquidations: binance.LiquidationStream | None = None
        self.last_fetch_at: datetime | None = None
        self.last_fetch_counts: dict[str, int] = {}

    # ------------------------------------------------------------------ config
    @staticmethod
    def config() -> dict[str, Any]:
        return config_store.get_config().get("market", {})

    def _client(self, exchange: str) -> ExchangeClient:
        if exchange not in self.clients:
            self.clients[exchange] = EXCHANGE_FACTORIES[exchange]()
        return self.clients[exchange]

    async def close(self) -> None:
        if self.liquidations:
            await self.liquidations.stop()
        await asyncio.gather(*(client.close() for client in self.clients.values()), return_exceptions=True)
        self.clients.clear()

    # ---------------------------------------------------------------- fetching
    async def fetch_candles_all_exchanges(self, limit: int = 120) -> dict[str, int]:
        """Fetch recent 1m candles for every asset/exchange concurrently and upsert them."""
        cfg = self.config()
        timeframe = cfg.get("candle_timeframe", "1m")
        pairs = [(asset, exchange) for asset in cfg.get("assets", []) for exchange in cfg.get("exchanges", []) if exchange in EXCHANGE_FACTORIES]
        results = await asyncio.gather(*(self._fetch_one(asset, exchange, timeframe, limit) for asset, exchange in pairs), return_exceptions=True)

        counts: dict[str, int] = {}
        with SessionLocal() as db:
            for (asset, exchange), result in zip(pairs, results):
                if isinstance(result, Exception):
                    log.error("{} {}: fetch failed - {}", exchange, asset, result)
                    continue
                counts[f"{exchange}:{asset}"] = self._upsert_candles(db, asset, exchange, timeframe, result)
            db.commit()
        self.last_fetch_at = utcnow()
        self.last_fetch_counts = counts
        log.info("Fetched {} candles across {} pairs", sum(counts.values()), len(counts))
        return counts

    async def _fetch_one(self, asset: str, exchange: str, timeframe: str, limit: int) -> list[list]:
        return await self._client(exchange).fetch_ohlcv(asset, timeframe=timeframe, limit=limit)

    async def fetch_commodities(self, interval: str = "5m") -> dict[str, int]:
        """yfinance commodity candles (stored under exchange ``yfinance``)."""
        tickers = self.config().get("commodities", [])
        results = await asyncio.gather(*(commodities.fetch_ohlcv(ticker, interval=interval) for ticker in tickers), return_exceptions=True)
        counts: dict[str, int] = {}
        with SessionLocal() as db:
            for ticker, rows in zip(tickers, results):
                if isinstance(rows, Exception):
                    log.error("yfinance {}: {}", ticker, rows)
                    continue
                counts[ticker] = self._upsert_candles(db, commodities.asset_code(ticker), commodities.EXCHANGE_NAME, interval, rows)
            db.commit()
        log.info("Fetched commodity candles: {}", counts)
        return counts

    @staticmethod
    def _upsert_candles(db: Session, asset: str, exchange: str, timeframe: str, rows: list[list]) -> int:
        if not rows:
            return 0
        values = [
            {
                "asset": asset,
                "exchange": exchange,
                "timeframe": timeframe,
                "timestamp": from_unix_ms(row[0]),
                "open": row[1],
                "high": row[2],
                "low": row[3],
                "close": row[4],
                "volume": row[5],
                "volume_usd": (row[5] or 0) * row[4],  # USD/USDT-quoted pairs -> base volume x close
                "created_at": utcnow(),
            }
            for row in rows
        ]
        statement = sqlite_insert(MarketCandle).values(values)
        # Re-fetched candles are identical; the newest (still open) candle is refreshed each minute
        statement = statement.on_conflict_do_update(
            index_elements=["asset", "exchange", "timeframe", "timestamp"],
            set_={c: statement.excluded[c] for c in ("open", "high", "low", "close", "volume", "volume_usd")},
        )
        db.execute(statement)
        return len(values)

    # ---------------------------------------------------------------- analysis
    def _load_frame(self, db: Session, asset: str, exchange: str, since: datetime):
        rows = db.execute(
            select(MarketCandle)
            .where(MarketCandle.asset == asset, MarketCandle.exchange == exchange, MarketCandle.timestamp >= since)
            .order_by(MarketCandle.timestamp)
        ).scalars()
        return candles_to_frame(rows)

    async def analyze_anomalies(self) -> int:
        """Run price/volume detectors for every asset/exchange and persist new alerts."""
        cfg = self.config()
        sigma = float(cfg.get("price_anomaly_sigma", 3.0))
        baseline_days = int(cfg.get("price_baseline_days", 7))
        multiplier = float(cfg.get("volume_spike_multiplier", 2.0))
        cooldown = timedelta(minutes=int(cfg.get("alert_cooldown_minutes", 30)))
        since = utcnow() - timedelta(days=baseline_days, hours=1)
        exchanges = list(cfg.get("exchanges", [])) + [commodities.EXCHANGE_NAME]
        assets = list(cfg.get("assets", [])) + [commodities.asset_code(t) for t in cfg.get("commodities", [])]

        created = 0
        with SessionLocal() as db:
            for asset in assets:
                for exchange in exchanges:
                    frame = self._load_frame(db, asset, exchange, since)
                    if frame.empty:
                        continue
                    anomalies = detect_price_anomalies(frame, exchange, sigma=sigma, baseline_points=baseline_days * 24 * 60)
                    anomalies += detect_volume_spikes(frame, exchange, multiplier=multiplier)
                    for anomaly in anomalies:
                        if self._persist_anomaly(db, asset, anomaly, cooldown):
                            created += 1
            db.commit()
        log.info("Anomaly analysis complete - {} new alert(s)", created)
        return created

    @staticmethod
    def _persist_anomaly(db: Session, asset: str, anomaly: Anomaly, cooldown: timedelta) -> bool:
        duplicate = db.execute(
            select(MarketAlert.id).where(
                MarketAlert.asset == asset,
                MarketAlert.alert_type == anomaly.type,
                MarketAlert.timestamp == anomaly.timestamp,
                MarketAlert.exchanges_involved == [anomaly.exchange],
            )
        ).first()
        if duplicate:
            return False
        # Cooldown: don't re-alert the same asset/exchange/type unless severity escalates
        recent = db.execute(
            select(MarketAlert)
            .where(
                MarketAlert.asset == asset,
                MarketAlert.alert_type == anomaly.type,
                MarketAlert.exchanges_involved == [anomaly.exchange],
                MarketAlert.timestamp >= anomaly.timestamp - cooldown,
            )
            .order_by(MarketAlert.timestamp.desc())
        ).scalars().first()
        rank = {"low": 0, "medium": 1, "high": 2, "critical": 3}
        if recent and rank.get(anomaly.severity, 0) <= rank.get(recent.severity, 0):
            return False
        db.add(
            MarketAlert(
                asset=asset,
                alert_type=anomaly.type,
                severity=anomaly.severity,
                exchanges_involved=[anomaly.exchange],
                price_at_alert=anomaly.price,
                price_change_percent=anomaly.change_percent,
                volume=anomaly.volume,
                volume_multiplier=anomaly.volume_multiplier,
                timestamp=anomaly.timestamp,
                confidence_score=anomaly.confidence,
                summary=anomaly.summary,
            )
        )
        log.warning("{} {} [{}] {}", asset, anomaly.type, anomaly.severity, anomaly.summary)
        notifications.send_alert("market", f"{asset} {anomaly.type.replace('_', ' ')} on {anomaly.exchange}", anomaly.summary, anomaly.severity, {"asset": asset, "price": anomaly.price})
        return True

    async def analyze_coordination(self) -> int:
        cfg = self.config()
        lookback = int(cfg.get("coordination_lookback_minutes", 60))
        since = utcnow() - timedelta(minutes=lookback + 30)
        created = 0
        with SessionLocal() as db:
            for asset in cfg.get("assets", []):
                frames = {ex: self._load_frame(db, asset, ex, since) for ex in cfg.get("exchanges", [])}
                events = detect_cross_exchange_coordination(
                    asset,
                    frames,
                    window_seconds=int(cfg.get("coordination_window_seconds", 30)),
                    min_correlation=float(cfg.get("coordination_min_correlation", 0.85)),
                    min_move_percent=float(cfg.get("coordination_min_move_percent", 2.0)),
                    lookback_minutes=lookback,
                )
                for event in events:
                    if self._persist_coordination(db, event):
                        created += 1
            db.commit()
        log.info("Coordination analysis complete - {} new event(s)", created)
        return created

    @staticmethod
    def _persist_coordination(db: Session, event: Coordination) -> bool:
        exists = db.execute(
            select(CoordinationEvent.id).where(CoordinationEvent.asset == event.asset, CoordinationEvent.detected_at == event.timestamp)
        ).first()
        if exists:
            return False
        severity = "critical" if event.confidence >= 0.8 else "high" if event.confidence >= 0.6 else "medium"
        db.add(
            CoordinationEvent(
                asset=event.asset,
                exchanges=event.exchanges,
                time_delta_seconds=event.time_delta_seconds,
                correlated_price_move=event.move_percent,
                volume_coordination=event.volume_coordination,
                confidence_score=event.confidence,
                detected_at=event.timestamp,
                investigation_status="flagged",
                summary=event.summary,
            )
        )
        db.add(
            MarketAlert(
                asset=event.asset,
                alert_type="coordination",
                severity=severity,
                exchanges_involved=event.exchanges,
                price_at_alert=event.price,
                price_change_percent=event.move_percent,
                volume_multiplier=event.volume_coordination,
                timestamp=event.timestamp,
                confidence_score=event.confidence,
                summary=event.summary,
            )
        )
        log.warning("{} coordination [{}] {}", event.asset, severity, event.summary)
        notifications.send_alert("coordination", f"{event.asset} cross-exchange coordination", event.summary, severity, {"exchanges": event.exchanges, "confidence": event.confidence})
        return True

    async def analyze_liquidations(self) -> int:
        """Cluster buffered liquidation events into cascades and persist them."""
        cfg = self.config()
        if not cfg.get("liquidations_enabled", True):
            return 0
        self.ensure_liquidation_stream()
        events = self.liquidations.drain() if self.liquidations else []
        if not events:
            return 0
        cascades = detect_cascades(
            events,
            gap_minutes=float(cfg.get("liquidation_gap_minutes", 2.0)),
            min_events=int(cfg.get("liquidation_min_events", 5)),
            min_total_usd=float(cfg.get("liquidation_min_total_usd", 1_000_000)),
        )
        created = 0
        with SessionLocal() as db:
            recent_alerts = db.execute(
                select(MarketAlert).where(MarketAlert.alert_type == "price_anomaly", MarketAlert.timestamp >= utcnow() - timedelta(hours=2))
            ).scalars().all()
            external = [(a.timestamp, f"{a.asset} price anomaly ({a.severity})") for a in recent_alerts]
            for cascade in cascades:
                correlate_with_events(cascade, [e for e in external if e[1].startswith(cascade.asset)])
                exists = db.execute(
                    select(LiquidationCascade.id).where(
                        LiquidationCascade.asset == cascade.asset,
                        LiquidationCascade.exchange == cascade.exchange,
                        LiquidationCascade.timestamp == cascade.start,
                    )
                ).first()
                if exists:
                    continue
                db.add(
                    LiquidationCascade(
                        asset=cascade.asset,
                        exchange=cascade.exchange,
                        initial_liquidation_usd=cascade.initial_usd,
                        cascade_liquidations=cascade.count - 1,
                        total_liquidated_usd=cascade.total_usd,
                        price_impact=cascade.price_impact_percent,
                        trigger_source=f"{cascade.dominant_side} liquidations",
                        timestamp=cascade.start,
                        correlation_score=cascade.correlation_score,
                        external_event=cascade.correlated_event,
                        summary=cascade.summary,
                    )
                )
                severity = "low"
                for level, threshold in zip(("low", "medium", "high", "critical"), LIQUIDATION_SEVERITY_USD):
                    if cascade.total_usd >= threshold:
                        severity = level
                db.add(
                    MarketAlert(
                        asset=cascade.asset,
                        alert_type="liquidation",
                        severity=severity,
                        exchanges_involved=[cascade.exchange],
                        price_at_alert=cascade.events[-1]["price"],
                        price_change_percent=cascade.price_impact_percent,
                        volume=cascade.total_usd,
                        timestamp=cascade.start,
                        confidence_score=min(0.99, 0.5 + cascade.count / 100),
                        summary=cascade.summary,
                    )
                )
                log.warning("{} liquidation cascade [{}] {}", cascade.asset, severity, cascade.summary)
                created += 1
            db.commit()
        return created

    def ensure_liquidation_stream(self) -> None:
        """Start (or restart) the Binance liquidation WebSocket consumer on the bot loop."""
        assets = set(self.config().get("assets", []))
        if self.liquidations is None:
            self.liquidations = binance.LiquidationStream(assets)
        self.liquidations.assets = {a.upper() for a in assets}
        self.liquidations.start()

    # ----------------------------------------------------------------- cleanup
    async def cleanup_old_data(self) -> int:
        retention = config_store.get_config().get("retention", {})
        days = int(retention.get("market_candles_days", 90))
        cutoff = utcnow() - timedelta(days=days)
        with SessionLocal() as db:
            result = db.execute(delete(MarketCandle).where(MarketCandle.timestamp < cutoff))
            purged = result.rowcount or 0
            policy = db.execute(select(DataRetentionPolicy).where(DataRetentionPolicy.data_type == "market_candles")).scalar_one_or_none()
            if policy is None:
                policy = DataRetentionPolicy(data_type="market_candles", retention_days=days)
                db.add(policy)
            policy.retention_days = days
            policy.last_purge_at = utcnow()
            policy.records_purged = purged
            if purged:
                db.add(
                    AuditLog(
                        action_type="retention_purge",
                        user_id="system",
                        rationale=f"Purged {purged} market candles older than {days} days",
                        supporting_data={"cutoff": cutoff.isoformat(), "records": purged},
                        source_systems=["bots.market"],
                        created_by="system",
                    )
                )
            db.commit()
        log.info("Retention purge: removed {} candles older than {} days", purged, days)
        return purged

    # ------------------------------------------------------------------ status
    def status(self) -> dict[str, Any]:
        with SessionLocal() as db:
            candles = db.execute(select(func.count(MarketCandle.id))).scalar() or 0
            open_alerts = db.execute(select(func.count(MarketAlert.id)).where(MarketAlert.acknowledged.is_(False))).scalar() or 0
        return {
            "last_fetch_at": self.last_fetch_at,
            "last_fetch_counts": self.last_fetch_counts,
            "candles_stored": candles,
            "open_alerts": open_alerts,
            "liquidation_stream": {
                "connected": bool(self.liquidations and self.liquidations.connected),
                "buffered_events": len(self.liquidations.events) if self.liquidations else 0,
                "last_event_at": self.liquidations.last_event_at if self.liquidations else None,
            },
        }


market_bot = MarketBot()
