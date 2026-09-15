"""/api/geopolitical/* - geopolitical events, correlations, timelines, sources."""

from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.bots.geopolitical import SEVERITY_RANK, geopolitical_bot
from app.bots.runtime import bot_loop
from app.database import get_db
from app.models.audit import AuditLog
from app.models.geopolitical import EventCorrelation, GeopoliticalEvent, NewsSource
from app.schemas.geopolitical import (
    CorrelationsResponse,
    EventCorrelationOut,
    EventsResponse,
    GeopoliticalEventDetail,
    GeopoliticalEventOut,
    NewsSourceOut,
    TimelineBucket,
    TimelineResponse,
    VerifyRequest,
)
from app.utils.serialization import jsonable
from app.utils.time import utcnow

router = APIRouter(tags=["geopolitical"])

EVENT_TYPES = ("conflict", "sanctions", "political", "trade", "port_closure", "infrastructure", "maritime_incident")


def _severities_at_or_above(min_severity: str) -> list[str]:
    floor = SEVERITY_RANK.get(min_severity, 0)
    return [s for s, rank in SEVERITY_RANK.items() if rank >= floor]


@router.get("/events", response_model=EventsResponse)
def list_events(
    hours: int = Query(24, ge=1, le=24 * 90),
    event_type: str | None = Query(None, description="Comma-separated subset of " + ", ".join(EVENT_TYPES)),
    country: str | None = Query(None, description="ISO alpha-2; matches primary, secondary or affected countries"),
    min_severity: str = Query("low", pattern="^(low|medium|high|critical)$"),
    source: str | None = None,
    correlated: bool | None = Query(None, description="Only events with (true) / without (false) cross-domain correlations"),
    q: str | None = Query(None, max_length=100, description="Free-text search in title / description"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> EventsResponse:
    since = utcnow() - timedelta(hours=hours)
    query = select(GeopoliticalEvent).where(GeopoliticalEvent.event_date >= since)
    if event_type:
        types = [t.strip() for t in event_type.split(",") if t.strip()]
        query = query.where(GeopoliticalEvent.event_type.in_(types))
    if country:
        iso = country.upper()
        query = query.where(
            or_(
                GeopoliticalEvent.country_primary == iso,
                GeopoliticalEvent.country_secondary == iso,
                cast(GeopoliticalEvent.affected_countries, String).like(f'%"{iso}"%'),
            )
        )
    if min_severity != "low":
        query = query.where(GeopoliticalEvent.severity.in_(_severities_at_or_above(min_severity)))
    if source:
        query = query.where(GeopoliticalEvent.source == source)
    if correlated is True:
        query = query.where(or_(GeopoliticalEvent.correlated_with_market.is_(True), GeopoliticalEvent.correlated_with_maritime.is_(True), GeopoliticalEvent.correlated_with_sanctions.is_(True)))
    elif correlated is False:
        query = query.where(GeopoliticalEvent.correlated_with_market.is_(False), GeopoliticalEvent.correlated_with_maritime.is_(False), GeopoliticalEvent.correlated_with_sanctions.is_(False))
    if q:
        pattern = f"%{q}%"
        query = query.where(or_(GeopoliticalEvent.title.ilike(pattern), GeopoliticalEvent.description.ilike(pattern)))
    total = db.execute(select(func.count()).select_from(query.subquery())).scalar() or 0
    rows = db.execute(query.order_by(GeopoliticalEvent.event_date.desc(), GeopoliticalEvent.id.desc()).limit(limit).offset(offset)).scalars().all()
    return EventsResponse(
        total=total,
        limit=limit,
        offset=offset,
        filters={"hours": hours, "event_type": event_type, "country": country, "min_severity": min_severity, "source": source, "correlated": correlated, "q": q},
        events=[GeopoliticalEventOut.model_validate(r) for r in rows],
    )


@router.get("/events/{event_id}", response_model=GeopoliticalEventDetail)
def get_event(event_id: int, db: Session = Depends(get_db)) -> GeopoliticalEventDetail:
    event = db.execute(select(GeopoliticalEvent).options(selectinload(GeopoliticalEvent.correlations)).where(GeopoliticalEvent.id == event_id)).scalar_one_or_none()
    if event is None:
        raise HTTPException(status_code=404, detail="Event not found")
    out = GeopoliticalEventDetail.model_validate(event)
    out.correlations = sorted((EventCorrelationOut.model_validate(c) for c in event.correlations), key=lambda c: -(c.correlation_score or 0))
    return out


@router.post("/events/{event_id}/verify", response_model=GeopoliticalEventOut)
def verify_event(event_id: int, body: VerifyRequest, db: Session = Depends(get_db)) -> GeopoliticalEventOut:
    event = db.get(GeopoliticalEvent, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Event not found")
    previous = event.verification_status
    event.verification_status = body.status
    if body.notes:
        event.intelligence_notes = ((event.intelligence_notes or "") + f"\n[{utcnow():%Y-%m-%d %H:%M}Z {body.analyst or 'analyst'}] {body.notes}").strip()
    db.add(
        AuditLog(
            action_type="event_verification",
            user_id=body.analyst or "analyst",
            rationale=body.notes or f"Verification status {previous} -> {body.status}",
            supporting_data={"event_id": event_id, "previous": previous, "new": body.status, "title": event.title},
            source_systems=["api.geopolitical"],
            created_by=body.analyst or "analyst",
        )
    )
    db.commit()
    db.refresh(event)
    return GeopoliticalEventOut.model_validate(event)


@router.get("/alerts", response_model=EventsResponse)
def list_alerts(hours: int = Query(48, ge=1, le=24 * 30), limit: int = Query(50, ge=1, le=200), db: Session = Depends(get_db)) -> EventsResponse:
    """High / critical events, correlated ones first."""
    since = utcnow() - timedelta(hours=hours)
    query = select(GeopoliticalEvent).where(GeopoliticalEvent.event_date >= since, GeopoliticalEvent.severity.in_(["high", "critical"]))
    total = db.execute(select(func.count()).select_from(query.subquery())).scalar() or 0
    rows = db.execute(
        query.order_by(
            (GeopoliticalEvent.correlated_with_market | GeopoliticalEvent.correlated_with_maritime | GeopoliticalEvent.correlated_with_sanctions).desc(),
            GeopoliticalEvent.event_date.desc(),
        ).limit(limit)
    ).scalars().all()
    return EventsResponse(total=total, limit=limit, offset=0, filters={"hours": hours, "min_severity": "high"}, events=[GeopoliticalEventOut.model_validate(r) for r in rows])


@router.get("/correlations", response_model=CorrelationsResponse)
def list_correlations(
    hours: int = Query(48, ge=1, le=24 * 30),
    alert_type: str | None = Query(None, pattern="^(market_alert|sanctions_breach|evasion_event|transshipment|sanctions_update)$"),
    min_score: float = Query(0.0, ge=0, le=1),
    limit: int = Query(200, ge=1, le=1000),
    db: Session = Depends(get_db),
) -> CorrelationsResponse:
    since = utcnow() - timedelta(hours=hours)
    query = select(EventCorrelation).where(EventCorrelation.detected_at >= since, EventCorrelation.correlation_score >= min_score)
    if alert_type:
        query = query.where(EventCorrelation.alert_type == alert_type)
    total = db.execute(select(func.count()).select_from(query.subquery())).scalar() or 0
    rows = db.execute(query.order_by(EventCorrelation.correlation_score.desc(), EventCorrelation.detected_at.desc()).limit(limit)).scalars().all()
    return CorrelationsResponse(hours=hours, total=total, correlations=[EventCorrelationOut.model_validate(r) for r in rows])


@router.get("/timeline/{country}", response_model=TimelineResponse)
def country_timeline(country: str, days: int = Query(30, ge=1, le=180), limit: int = Query(200, ge=1, le=1000), db: Session = Depends(get_db)) -> TimelineResponse:
    iso = country.upper()
    if len(iso) != 2:
        raise HTTPException(status_code=400, detail="country must be an ISO alpha-2 code")
    since = utcnow() - timedelta(days=days)
    rows = db.execute(
        select(GeopoliticalEvent)
        .where(GeopoliticalEvent.event_date >= since, or_(GeopoliticalEvent.country_primary == iso, GeopoliticalEvent.country_secondary == iso))
        .order_by(GeopoliticalEvent.event_date.desc())
        .limit(limit)
    ).scalars().all()
    buckets: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = row.event_date.strftime("%Y-%m-%d")
        bucket = buckets.setdefault(key, {"day": row.event_date.replace(hour=0, minute=0, second=0, microsecond=0), "total": 0, "by_type": {}, "max_severity": None})
        bucket["total"] += 1
        bucket["by_type"][row.event_type] = bucket["by_type"].get(row.event_type, 0) + 1
        if SEVERITY_RANK.get(row.severity, 0) >= SEVERITY_RANK.get(bucket["max_severity"], -1):
            bucket["max_severity"] = row.severity
    return TimelineResponse(
        country=iso,
        days=days,
        total=len(rows),
        buckets=[TimelineBucket(**b) for _, b in sorted(buckets.items())],
        events=[GeopoliticalEventOut.model_validate(r) for r in rows],
    )


@router.get("/geojson")
def events_geojson(hours: int = Query(48, ge=1, le=24 * 30), min_severity: str = Query("low", pattern="^(low|medium|high|critical)$"), db: Session = Depends(get_db)) -> dict[str, Any]:
    since = utcnow() - timedelta(hours=hours)
    query = select(GeopoliticalEvent).where(GeopoliticalEvent.event_date >= since, GeopoliticalEvent.coordinates_lat.is_not(None), GeopoliticalEvent.coordinates_lon.is_not(None))
    if min_severity != "low":
        query = query.where(GeopoliticalEvent.severity.in_(_severities_at_or_above(min_severity)))
    rows = db.execute(query.order_by(GeopoliticalEvent.event_date.desc()).limit(2000)).scalars().all()
    features = [
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [r.coordinates_lon, r.coordinates_lat]},
            "properties": jsonable({"id": r.id, "title": r.title, "event_type": r.event_type, "severity": r.severity, "country": r.country_primary, "event_date": r.event_date, "mentions": r.mentions, "source": r.source}),
        }
        for r in rows
    ]
    return {"type": "FeatureCollection", "features": features}


@router.get("/summary")
def summary(hours: int = Query(24, ge=1, le=24 * 30), db: Session = Depends(get_db)) -> dict[str, Any]:
    return jsonable(geopolitical_bot.summary(db, hours))


@router.get("/sources", response_model=list[NewsSourceOut])
def list_sources(db: Session = Depends(get_db)) -> list[NewsSourceOut]:
    rows = db.execute(select(NewsSource).order_by(NewsSource.source_name)).scalars().all()
    return [NewsSourceOut.model_validate(r) for r in rows]


@router.get("/status")
def get_status() -> dict[str, Any]:
    return jsonable(geopolitical_bot.status())


@router.post("/refresh", status_code=202)
def trigger_refresh(job: str = Query("all", pattern="^(all|gdelt|doc|feeds|correlate)$")) -> dict[str, Any]:
    """Run a collection job now on the bot loop; poll /status for the outcome."""
    jobs = {"gdelt": geopolitical_bot.fetch_gdelt_events, "doc": geopolitical_bot.fetch_topic_articles, "feeds": geopolitical_bot.fetch_official_feeds, "correlate": geopolitical_bot.correlate}
    selected = list(jobs) if job == "all" else [job]
    for name in selected:
        bot_loop.submit(jobs[name]())
    return {"status": "started", "jobs": selected}
