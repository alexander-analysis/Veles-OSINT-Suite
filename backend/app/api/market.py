"""/api/market/* - market intelligence endpoints."""

from datetime import timedelta
from typing import Any

import csv
import io
from typing import Literal

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Response
from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.api import market_queries as queries
from app.database import get_db
from app.models.audit import AuditLog
from app.models.market import CoordinationEvent, MarketAlert, MarketCandle
from app.schemas.market import (
    AcknowledgeRequest,
    AlertOut,
    AlertsResponse,
    BotStatus,
    CoordinationOut,
    CoordinationResponse,
    CoordinationUpdate,
    HistoryResponse,
    PriceQuote,
    PricesResponse,
    VolatilityResponse,
)
from app.reports.intelligence import market_report
from app.reports.pdf import build_pdf
from app.utils import config_store
from app.utils.serialization import jsonable
from app.utils.time import utcnow

router = APIRouter(tags=["market"])


def _csv(value: str | None) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()] if value else []


@router.get("/prices", response_model=PricesResponse, response_model_by_alias=True)
def get_prices(
    assets: str | None = Query(None, description="Comma-separated assets, e.g. BTC,ETH"),
    exchanges: str | None = Query(None, description="Comma-separated exchanges, e.g. binance,kraken"),
    db: Session = Depends(get_db),
) -> PricesResponse:
    """Latest price per (asset, exchange) from the newest stored candle, with 24h change and volume."""
    latest = (
        select(MarketCandle.asset, MarketCandle.exchange, func.max(MarketCandle.timestamp).label("timestamp"))
        .group_by(MarketCandle.asset, MarketCandle.exchange)
        .subquery()
    )
    query = select(MarketCandle).join(
        latest,
        and_(
            MarketCandle.asset == latest.c.asset,
            MarketCandle.exchange == latest.c.exchange,
            MarketCandle.timestamp == latest.c.timestamp,
        ),
    )
    if wanted := _csv(assets):
        query = query.where(MarketCandle.asset.in_([a.upper() for a in wanted]))
    if wanted := _csv(exchanges):
        query = query.where(MarketCandle.exchange.in_([e.lower() for e in wanted]))
    candles = db.execute(query.order_by(MarketCandle.asset, MarketCandle.exchange)).scalars().all()

    data = []
    for candle in candles:
        change, volume_24h = queries.change_and_volume_24h(db, candle)
        data.append(
            PriceQuote(
                asset=candle.asset,
                exchange=candle.exchange,
                price=candle.close,
                change_24h_percent=change,
                timestamp=candle.timestamp,
                volume_24h_usd=volume_24h,
                signal_quality=queries.signal_quality(candle.timestamp),
            )
        )
    return PricesResponse(timestamp=utcnow(), data=data)


@router.get("/alerts", response_model=AlertsResponse)
def get_alerts(
    severity: str | None = Query(None, description="Comma-separated: low,medium,high,critical"),
    asset: str | None = None,
    alert_type: str | None = Query(None, description="price_anomaly, volume_spike, coordination, liquidation"),
    acknowledged: bool | None = None,
    hours: int | None = Query(None, ge=1, description="Only alerts from the last N hours"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> AlertsResponse:
    query = select(MarketAlert)
    if severities := _csv(severity):
        query = query.where(MarketAlert.severity.in_(severities))
    if asset:
        query = query.where(MarketAlert.asset == asset.upper())
    if alert_type:
        query = query.where(MarketAlert.alert_type == alert_type)
    if acknowledged is not None:
        query = query.where(MarketAlert.acknowledged.is_(acknowledged))
    if hours:
        query = query.where(MarketAlert.timestamp >= utcnow() - timedelta(hours=hours))
    total = db.execute(select(func.count()).select_from(query.subquery())).scalar() or 0
    rows = db.execute(query.order_by(MarketAlert.timestamp.desc()).limit(limit).offset(offset)).scalars().all()
    return AlertsResponse(total=total, limit=limit, offset=offset, alerts=[AlertOut.model_validate(r) for r in rows])


@router.post("/alerts/{alert_id}/acknowledge", response_model=AlertOut)
def acknowledge_alert(alert_id: int, body: AcknowledgeRequest, db: Session = Depends(get_db)) -> AlertOut:
    alert = db.get(MarketAlert, alert_id)
    if alert is None:
        raise HTTPException(status_code=404, detail="Alert not found")
    alert.acknowledged = True
    alert.acknowledged_by = body.acknowledged_by
    alert.acknowledged_at = utcnow()
    if body.notes:
        alert.notes = body.notes
    db.add(
        AuditLog(
            action_type="alert_acknowledged",
            user_id=body.acknowledged_by,
            rationale=body.notes or f"Market alert {alert_id} acknowledged",
            supporting_data={"alert_id": alert_id, "asset": alert.asset, "alert_type": alert.alert_type, "severity": alert.severity},
            source_systems=["api.market"],
            created_by=body.acknowledged_by,
        )
    )
    db.commit()
    db.refresh(alert)
    return AlertOut.model_validate(alert)


@router.get("/coordination", response_model=CoordinationResponse)
def get_coordination(
    asset: str | None = None,
    status: str | None = Query(None, description="flagged, investigating, cleared, escalated"),
    min_confidence: float = Query(0.0, ge=0, le=1),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
) -> CoordinationResponse:
    query = select(CoordinationEvent).where(CoordinationEvent.confidence_score >= min_confidence)
    if asset:
        query = query.where(CoordinationEvent.asset == asset.upper())
    if status:
        query = query.where(CoordinationEvent.investigation_status == status)
    total = db.execute(select(func.count()).select_from(query.subquery())).scalar() or 0
    rows = db.execute(query.order_by(CoordinationEvent.detected_at.desc()).limit(limit)).scalars().all()
    return CoordinationResponse(total=total, events=[CoordinationOut.model_validate(r) for r in rows])


@router.patch("/coordination/{event_id}", response_model=CoordinationOut)
def update_coordination(event_id: int, body: CoordinationUpdate, db: Session = Depends(get_db)) -> CoordinationOut:
    event = db.get(CoordinationEvent, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Coordination event not found")
    changes: dict[str, Any] = {}
    if body.investigation_status and body.investigation_status != event.investigation_status:
        changes["investigation_status"] = [event.investigation_status, body.investigation_status]
        event.investigation_status = body.investigation_status
    if body.analyst_notes is not None:
        changes["analyst_notes"] = body.analyst_notes
        event.analyst_notes = body.analyst_notes
    if changes:
        db.add(
            AuditLog(
                action_type=f"coordination_{body.investigation_status or 'annotated'}",
                user_id=body.updated_by,
                rationale=body.analyst_notes or f"Coordination event {event_id} updated",
                supporting_data={"event_id": event_id, "asset": event.asset, "changes": changes},
                source_systems=["api.market"],
                created_by=body.updated_by,
            )
        )
        db.commit()
        db.refresh(event)
    return CoordinationOut.model_validate(event)


@router.get("/history/{asset}", response_model=HistoryResponse)
def get_history(
    asset: str,
    timeframe: str = Query("1m", pattern=r"^(1m|5m|15m|1h|4h|1d)$"),
    hours: int | None = Query(None, ge=1, le=24 * 90),
    days: int | None = Query(None, ge=1, le=90),
    exchanges: str | None = Query(None, description="Comma-separated; default: all with data"),
    db: Session = Depends(get_db),
) -> HistoryResponse:
    """Candles pivoted by exchange (resampled server-side when timeframe > 1m) plus alerts in the period."""
    span = timedelta(days=days) if days else timedelta(hours=hours or 6)
    end = utcnow()
    start = end - span
    wanted = [e.lower() for e in _csv(exchanges)]
    candles, used = queries.history_candles(db, asset.upper(), start, end, timeframe, wanted)
    alerts = db.execute(
        select(MarketAlert).where(MarketAlert.asset == asset.upper(), MarketAlert.timestamp.between(start, end)).order_by(MarketAlert.timestamp)
    ).scalars().all()
    return HistoryResponse(
        asset=asset.upper(),
        timeframe=timeframe,
        period=f"{start.replace(microsecond=0).isoformat()}Z to {end.replace(microsecond=0).isoformat()}Z",
        exchanges=used,
        candles=candles,
        anomalies_in_period=[
            {
                "id": a.id,
                "timestamp": f"{a.timestamp.replace(microsecond=0).isoformat()}Z",
                "type": a.alert_type,
                "severity": a.severity,
                "price": a.price_at_alert,
                "exchanges": a.exchanges_involved,
                "multiplier": a.volume_multiplier,
                "change_percent": a.price_change_percent,
                "summary": a.summary,
            }
            for a in alerts
        ],
    )


@router.get("/volatility/{asset}", response_model=VolatilityResponse)
def get_volatility(
    asset: str,
    hours: int = Query(24, ge=1, le=24 * 30),
    window_minutes: int = Query(15, ge=5, le=240),
    db: Session = Depends(get_db),
) -> VolatilityResponse:
    """Realised volatility per exchange, high-volatility clusters and a rolling series for charts."""
    cfg = config_store.get_config().get("market", {})
    result = queries.volatility(
        db,
        asset.upper(),
        hours=hours,
        window_minutes=window_minutes,
        cluster_multiplier=float(cfg.get("volatility_cluster_multiplier", 2.0)),
        extreme_move_percent=float(cfg.get("volatility_extreme_move_percent", 20.0)),
    )
    return VolatilityResponse(asset=asset.upper(), hours=hours, window_minutes=window_minutes, **result)


@router.post("/config")
def update_market_config(
    patch: dict[str, Any] = Body(..., description="Partial `market` section, e.g. {\"assets\": [\"BTC\", \"ETH\", \"SOL\"]}"),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Update monitored assets, exchanges and thresholds (takes effect on the bots' next run)."""
    if not patch:
        raise HTTPException(status_code=422, detail="Empty patch")
    merged = config_store.update_config({"market": patch})
    db.add(
        AuditLog(
            action_type="config_updated",
            user_id="anonymous",
            rationale="Market configuration updated via POST /api/market/config",
            supporting_data={"patch": {"market": patch}},
            source_systems=["api.market"],
            created_by="anonymous",
        )
    )
    db.commit()
    return merged["market"]


@router.get("/export/{timerange}")
def export_market_report(timerange: str, format: Literal["json", "pdf", "csv"] = "json", classification: str = Query("UNCLASSIFIED", max_length=50), db: Session = Depends(get_db)):
    """Market intelligence brief for ``24h`` / ``7d`` / ``30d`` as JSON, PDF or CSV (alerts), audited as an export."""
    unit = timerange[-1]
    try:
        amount = int(timerange[:-1])
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="timerange like 24h, 7d or 30d") from exc
    end = utcnow()
    start = end - (timedelta(days=amount) if unit == "d" else timedelta(hours=amount))
    report, data = market_report(db, start, end, classification)
    db.add(AuditLog(action_type="export", user_id="anonymous", rationale=f"Market intelligence brief ({format}, {timerange})", supporting_data={"format": format, "classification": classification}, source_systems=["api.market"], created_by="anonymous"))
    db.commit()
    stamp = end.strftime("%Y-%m-%d")
    if format == "pdf":
        return Response(build_pdf(report), media_type="application/pdf", headers={"Content-Disposition": f"attachment; filename=VELES_Market_Brief_{stamp}.pdf"})
    if format == "csv":
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(["timestamp", "asset", "type", "severity", "exchanges", "change_percent", "confidence", "acknowledged", "summary"])
        for a in data["alerts"]:
            writer.writerow([a["timestamp"], a["asset"], a["type"], a["severity"], ";".join(a["exchanges"] or []), a["change_percent"], a["confidence"], a["acknowledged"], a["summary"]])
        return Response(buffer.getvalue(), media_type="text/csv", headers={"Content-Disposition": f"attachment; filename=VELES_Market_Alerts_{stamp}.csv"})
    return jsonable(data)


@router.get("/status", response_model=BotStatus)
def get_status() -> BotStatus:
    """Market bot runtime status (fetch times, stream state, counts)."""
    from app.bots.market import market_bot

    return BotStatus(**market_bot.status())
