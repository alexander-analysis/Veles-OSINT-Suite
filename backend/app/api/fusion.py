"""/api/fusion/* - cross-bot correlation engine: unified queue, composite alerts, pairwise correlations, timeline."""

from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.analysis.correlation_engine import SEVERITY_RANK
from app.bots.correlation import correlation_engine
from app.bots.runtime import bot_loop
from app.database import get_db
from app.models.audit import AuditLog
from app.models.correlation import CompositeAlert, SignalCorrelation
from app.reports.fusion_brief import fusion_brief
from app.reports.pdf import build_pdf
from app.schemas.common import APIModel
from app.utils.serialization import jsonable
from app.utils.time import utcnow

router = APIRouter(tags=["fusion"])


class CompositeAlertOut(APIModel):
    id: int
    title: str
    domains: list[str]
    signals: list[dict[str, Any]]
    shared_keys: list[str] | None = None
    window_start: datetime
    window_end: datetime
    confidence: float | None = None
    severity: str | None = None
    intelligence_summary: str | None = None
    acknowledged: bool = False
    acknowledged_by: str | None = None
    detected_at: datetime
    fingerprint: str | None = None


class SignalCorrelationOut(APIModel):
    id: int
    signal_a_type: str
    signal_a_id: int
    signal_a_summary: str | None = None
    signal_a_time: datetime
    signal_b_type: str
    signal_b_id: int
    signal_b_summary: str | None = None
    signal_b_time: datetime
    correlation_type: str | None = None
    time_delta_minutes: int | None = None
    shared_keys: list[str] | None = None
    confidence: float | None = None
    rationale: str | None = None
    detected_at: datetime


@router.get("/queue")
def queue(hours: int = Query(24, ge=1, le=24 * 14), min_severity: str = Query("low", pattern="^(low|medium|high|critical)$"), domains: str | None = Query(None, description="Comma-separated: market, maritime, sanctions, geopolitical, blockchain, corporate, energy"),
          limit: int = Query(200, ge=1, le=1000), db: Session = Depends(get_db)) -> dict[str, Any]:
    """Every signal from every bot in one ranked list (severity, then correlation count, then recency)."""
    selected = [d.strip() for d in domains.split(",") if d.strip()] if domains else None
    return jsonable(correlation_engine.queue(db, hours, min_severity, selected, limit))


@router.get("/composite-alerts", response_model=list[CompositeAlertOut])
def composite_alerts(hours: int = Query(24 * 7, ge=1, le=24 * 90), acknowledged: bool | None = None, min_severity: str = Query("low", pattern="^(low|medium|high|critical)$"), limit: int = Query(100, ge=1, le=500), db: Session = Depends(get_db)) -> list[CompositeAlertOut]:
    query = select(CompositeAlert).where(CompositeAlert.detected_at >= utcnow() - timedelta(hours=hours))
    if acknowledged is not None:
        query = query.where(CompositeAlert.acknowledged.is_(acknowledged))
    floor = SEVERITY_RANK.get(min_severity, 0)
    if floor:
        query = query.where(CompositeAlert.severity.in_([s for s, r in SEVERITY_RANK.items() if r >= floor]))
    rows = db.execute(query.order_by(CompositeAlert.detected_at.desc()).limit(limit)).scalars().all()
    rows.sort(key=lambda a: (-SEVERITY_RANK.get(a.severity, 0), -(a.confidence or 0)))
    return [CompositeAlertOut.model_validate(r) for r in rows]


@router.get("/composite-alerts/{alert_id}", response_model=CompositeAlertOut)
def composite_alert(alert_id: int, db: Session = Depends(get_db)) -> CompositeAlertOut:
    row = db.get(CompositeAlert, alert_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Composite alert not found")
    return CompositeAlertOut.model_validate(row)


@router.post("/composite-alerts/{alert_id}/acknowledge", response_model=CompositeAlertOut)
def acknowledge(alert_id: int, analyst: str | None = Query(None, max_length=100), notes: str | None = Query(None, max_length=500), db: Session = Depends(get_db)) -> CompositeAlertOut:
    row = db.get(CompositeAlert, alert_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Composite alert not found")
    row.acknowledged = True
    row.acknowledged_by = analyst or "analyst"
    db.add(AuditLog(action_type="alert_acknowledged", user_id=analyst or "analyst", rationale=notes or f"Composite alert acknowledged: {row.title}", supporting_data={"alert_id": alert_id, "domains": row.domains}, source_systems=["api.fusion"], created_by=analyst or "analyst"))
    db.commit()
    db.refresh(row)
    return CompositeAlertOut.model_validate(row)


@router.get("/correlations", response_model=list[SignalCorrelationOut])
def correlations(hours: int = Query(48, ge=1, le=24 * 30), correlation_type: str | None = Query(None, description="e.g. maritime_energy, market_geopolitical"), signal_type: str | None = None, min_confidence: float = Query(0.0, ge=0, le=1),
                 limit: int = Query(200, ge=1, le=2000), db: Session = Depends(get_db)) -> list[SignalCorrelationOut]:
    query = select(SignalCorrelation).where(SignalCorrelation.detected_at >= utcnow() - timedelta(hours=hours), SignalCorrelation.confidence >= min_confidence)
    if correlation_type:
        query = query.where(SignalCorrelation.correlation_type == correlation_type)
    if signal_type:
        query = query.where((SignalCorrelation.signal_a_type == signal_type) | (SignalCorrelation.signal_b_type == signal_type))
    rows = db.execute(query.order_by(SignalCorrelation.confidence.desc(), SignalCorrelation.detected_at.desc()).limit(limit)).scalars().all()
    return [SignalCorrelationOut.model_validate(r) for r in rows]


@router.get("/timeline")
def timeline(hours: int = Query(48, ge=1, le=24 * 14), bucket_hours: int = Query(1, ge=1, le=24), db: Session = Depends(get_db)) -> dict[str, Any]:
    return jsonable(correlation_engine.timeline(db, hours, bucket_hours))


@router.get("/summary")
def summary(hours: int = Query(24, ge=1, le=24 * 30), db: Session = Depends(get_db)) -> dict[str, Any]:
    out = correlation_engine.summary(db, hours)
    out["stored_alerts_total"] = db.execute(select(func.count(CompositeAlert.id))).scalar() or 0
    return jsonable(out)


@router.get("/brief")
def brief(hours: int = Query(24, ge=1, le=24 * 30), format: str = Query("json", pattern="^(json|pdf)$"), classification: str = Query("UNCLASSIFIED", max_length=50), db: Session = Depends(get_db)):
    """Cross-domain intelligence brief for the last N hours (JSON or PDF)."""
    end = utcnow()
    report, data = fusion_brief(db, end - timedelta(hours=hours), end, classification)
    if format == "pdf":
        return Response(build_pdf(report), media_type="application/pdf", headers={"Content-Disposition": f"attachment; filename=VELES_Intelligence_Brief_{end:%Y-%m-%d}.pdf"})
    return jsonable(data)


@router.get("/status")
def get_status() -> dict[str, Any]:
    return jsonable(correlation_engine.status())


@router.post("/refresh", status_code=202)
def trigger_refresh() -> dict[str, Any]:
    bot_loop.submit(correlation_engine.run())
    return {"status": "started"}
