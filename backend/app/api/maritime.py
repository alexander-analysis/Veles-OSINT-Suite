"""/api/maritime/* - vessels, breaches, evasion, transshipment, ports, lanes, audit log."""

import csv
import io
import json
from datetime import timedelta
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.orm import Session

from app.analysis.correlation import correlated_vessels, fleet_groups
from app.analysis.risk import compute_risk_score
from app.data.ports import PORTS
from app.data.zones import lanes_geojson, zones_geojson
from app.database import get_db
from app.models.audit import AuditLog
from app.models.maritime import EvasionEvent, PortCallEvent, SanctionsBreach, ShippingLaneViolation, TransshipmentEvent, Vessel, VesselPosition
from app.schemas.maritime import (
    AuditEntryOut,
    AuditLogResponse,
    BreachListResponse,
    BreachOut,
    EvasionOut,
    ExportRequest,
    InvestigationUpdate,
    LaneViolationOut,
    PointGeometry,
    PortCallOut,
    TransshipmentOut,
    VesselFeature,
    VesselFeatureCollection,
    VesselListResponse,
    VesselProperties,
    VesselSummary,
)
from app.reports.intelligence import maritime_report
from app.reports.pdf import build_pdf
from app.utils.serialization import jsonable
from app.utils.time import to_iso_z, utcnow

router = APIRouter(tags=["maritime"])

MARKER_COLORS = {"clear": "#2ecc71", "flagged": "#f39c12", "breach": "#e74c3c"}


def marker_color(sanctioned_status: str | None) -> str:
    if sanctioned_status and sanctioned_status.startswith("breach"):
        return MARKER_COLORS["breach"]
    if sanctioned_status == "flagged":
        return MARKER_COLORS["flagged"]
    return MARKER_COLORS["clear"]


def _csv(value: str | None) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()] if value else []


def parse_bbox(value: str) -> tuple[float, float, float, float]:
    try:
        parts = [float(part) for part in value.split(",")]
    except ValueError:
        parts = []
    if len(parts) != 4:
        raise HTTPException(status_code=422, detail="bbox must be 'min_lon,min_lat,max_lon,max_lat'")
    min_lon, min_lat, max_lon, max_lat = parts
    if not (-180 <= min_lon <= max_lon <= 180 and -90 <= min_lat <= max_lat <= 90):
        raise HTTPException(status_code=422, detail="bbox out of range or min > max")
    return min_lon, min_lat, max_lon, max_lat


def _vessel_or_404(db: Session, mmsi: str) -> Vessel:
    vessel = db.execute(select(Vessel).where(Vessel.mmsi == mmsi)).scalar_one_or_none()
    if vessel is None:
        raise HTTPException(status_code=404, detail="Vessel not tracked")
    return vessel


def _audit(db: Session, action: str, user: str, rationale: str, vessel_id: int | None = None, breach_id: int | None = None, data: dict | None = None) -> None:
    db.add(AuditLog(action_type=action, user_id=user, vessel_id=vessel_id, breach_id=breach_id, rationale=rationale, supporting_data=data, source_systems=["api.maritime"], created_by=user))


# ------------------------------------------------------------------- vessels
@router.get("/vessels", response_model=VesselFeatureCollection)
def get_vessels(
    bbox: str = Query("-180,-90,180,90", description="min_lon,min_lat,max_lon,max_lat"),
    risk_filter: Literal["all", "flagged", "breach"] = Query("all"),
    max_age_hours: int = Query(24, ge=1, le=24 * 30, description="Hide vessels not heard from for longer than this"),
    limit: int = Query(5000, ge=1, le=20000),
    db: Session = Depends(get_db),
) -> VesselFeatureCollection:
    """Current vessel positions as a GeoJSON FeatureCollection."""
    min_lon, min_lat, max_lon, max_lat = parse_bbox(bbox)
    query = select(Vessel).where(
        Vessel.current_position_lat.between(min_lat, max_lat),
        Vessel.current_position_lon.between(min_lon, max_lon),
        Vessel.last_ais_update >= utcnow() - timedelta(hours=max_age_hours),
    )
    if risk_filter == "breach":
        query = query.where(Vessel.sanctioned_status.like("breach%"))
    elif risk_filter == "flagged":
        query = query.where(or_(Vessel.sanctioned_status == "flagged", Vessel.sanctioned_status.like("breach%")))
    vessels = db.execute(query.order_by(Vessel.risk_score.desc().nullslast(), Vessel.last_ais_update.desc()).limit(limit)).scalars().all()
    features = [
        VesselFeature(
            geometry=PointGeometry(coordinates=(v.current_position_lon, v.current_position_lat)),
            properties=VesselProperties(
                mmsi=v.mmsi, imo=v.imo, name=v.name, flag=v.flag_state, owner=v.owner_name, ship_type=v.ship_type, destination=v.destination,
                speed=v.current_speed, heading=v.current_heading, ais_status=v.ais_status, sanctioned_status=v.sanctioned_status or "clear",
                risk_score=v.risk_score, last_update=v.last_ais_update, ais_source=v.ais_source, marker_color=marker_color(v.sanctioned_status),
            ),
        )
        for v in vessels
    ]
    breach_count = sum(1 for v in vessels if (v.sanctioned_status or "").startswith("breach"))
    return VesselFeatureCollection(timestamp=utcnow(), vessel_count=len(features), breach_count=breach_count, features=features)


@router.get("/vessels/table", response_model=VesselListResponse)
def list_vessels(
    q: str | None = Query(None, description="Name / MMSI / IMO / owner substring"),
    flag: str | None = None,
    status: str | None = Query(None, description="clear, flagged, breach"),
    min_risk: float = Query(0.0, ge=0, le=1),
    max_age_hours: int = Query(24 * 7, ge=1),
    sort: Literal["risk", "recent", "name"] = "risk",
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> VesselListResponse:
    stmt = select(Vessel).where(Vessel.last_ais_update >= utcnow() - timedelta(hours=max_age_hours))
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(Vessel.name.ilike(like), Vessel.mmsi.like(like), Vessel.imo.like(like), Vessel.owner_name.ilike(like)))
    if flag:
        stmt = stmt.where(Vessel.flag_state == flag.upper())
    if status == "breach":
        stmt = stmt.where(Vessel.sanctioned_status.like("breach%"))
    elif status:
        stmt = stmt.where(Vessel.sanctioned_status == status)
    if min_risk > 0:
        stmt = stmt.where(Vessel.risk_score >= min_risk)
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar() or 0
    order = {"risk": Vessel.risk_score.desc().nullslast(), "recent": Vessel.last_ais_update.desc(), "name": Vessel.name.asc()}[sort]
    rows = db.execute(stmt.order_by(order, Vessel.id).limit(limit).offset(offset)).scalars().all()
    return VesselListResponse(total=total, limit=limit, offset=offset, vessels=[VesselSummary.model_validate(v) for v in rows])


@router.get("/vessel/{mmsi}")
def vessel_profile(mmsi: str, positions: int = Query(500, ge=1, le=5000), db: Session = Depends(get_db)) -> dict[str, Any]:
    """Complete intelligence profile: identity, matches, ports, track, linked vessels, audit history."""
    vessel = _vessel_or_404(db, mmsi)
    track = db.execute(select(VesselPosition).where(VesselPosition.vessel_id == vessel.id).order_by(VesselPosition.timestamp.desc()).limit(positions)).scalars().all()
    breaches = db.execute(select(SanctionsBreach).where(SanctionsBreach.vessel_id == vessel.id).order_by(SanctionsBreach.match_confidence.desc())).scalars().all()
    port_calls = db.execute(select(PortCallEvent).where(PortCallEvent.vessel_id == vessel.id).order_by(PortCallEvent.arrival_time.desc()).limit(50)).scalars().all()
    evasion = db.execute(select(EvasionEvent).where(EvasionEvent.vessel_id == vessel.id).order_by(EvasionEvent.timestamp.desc()).limit(50)).scalars().all()
    sts = db.execute(select(TransshipmentEvent).where(or_(TransshipmentEvent.vessel_a_id == vessel.id, TransshipmentEvent.vessel_b_id == vessel.id)).order_by(TransshipmentEvent.timestamp.desc()).limit(20)).scalars().all()
    lanes = db.execute(select(ShippingLaneViolation).where(ShippingLaneViolation.vessel_id == vessel.id).order_by(ShippingLaneViolation.timestamp.desc()).limit(50)).scalars().all()
    audit = db.execute(select(AuditLog).where(AuditLog.vessel_id == vessel.id).order_by(AuditLog.timestamp.desc()).limit(100)).scalars().all()
    score, factors = compute_risk_score(db, vessel)
    return jsonable(
        {
            "vessel": {
                **VesselSummary.model_validate(vessel).model_dump(),
                "call_sign": vessel.call_sign,
                "registered_operator": vessel.registered_operator,
                "beneficial_owner": vessel.beneficial_owner,
                "gross_tonnage": vessel.gross_tonnage,
                "historical_names": vessel.historical_names or [],
                "historical_flags": vessel.historical_flags or [],
                "current_heading": vessel.current_heading,
                "last_port_time": vessel.last_port_time,
                "created_at": vessel.created_at,
                "risk_factors": factors,
                "risk_score": score,
            },
            "sanctions_matches": [BreachOut.model_validate(_breach_view(b)).model_dump() for b in breaches],
            "port_history": [PortCallOut.model_validate(_port_view(c, vessel)).model_dump() for c in port_calls],
            "evasion_events": [EvasionOut.model_validate(_evasion_view(e, vessel)).model_dump() for e in evasion],
            "transshipments": [_sts_view(e).model_dump() for e in sts],
            "lane_events": [LaneViolationOut.model_validate(_lane_view(lane, vessel)).model_dump() for lane in lanes],
            "position_timeline": [
                {"timestamp": p.timestamp, "lat": p.latitude, "lon": p.longitude, "speed": p.speed, "heading": p.heading, "course": p.course, "source": p.ais_source}
                for p in reversed(track)
            ],
            "correlated_vessels": correlated_vessels(db, vessel),
            "audit_history": [AuditEntryOut.model_validate(a).model_dump() for a in audit],
        }
    )


@router.get("/vessel-correlation/{mmsi}")
def vessel_correlation(mmsi: str, days: int = Query(30, ge=1, le=365), db: Session = Depends(get_db)) -> dict[str, Any]:
    vessel = _vessel_or_404(db, mmsi)
    return jsonable({"vessel": VesselSummary.model_validate(vessel).model_dump(), "days": days, "linked": correlated_vessels(db, vessel, days=days)})


@router.get("/fleets")
def fleets(min_size: int = Query(2, ge=2), db: Session = Depends(get_db)) -> dict[str, Any]:
    """Vessel groups sharing a declared owner / operator / beneficial owner."""
    return jsonable({"groups": fleet_groups(db, min_size=min_size)})


# ------------------------------------------------------------------ breaches
def _breach_view(b: SanctionsBreach) -> dict[str, Any]:
    return {
        **{c.name: getattr(b, c.name) for c in SanctionsBreach.__table__.columns},
        "location": {"lat": b.location_lat, "lon": b.location_lon, "description": b.location_description} if b.location_lat is not None else None,
    }


@router.get("/breaches", response_model=BreachListResponse)
def get_breaches(
    authority: str | None = Query(None, description="Comma-separated: OFAC,EU,UN"),
    severity: str | None = Query(None, description="Comma-separated: critical,high,medium,low"),
    status: str | None = Query(None, description="Comma-separated: flagged,review,investigating,cleared,escalated"),
    breach_type: str | None = None,
    min_confidence: float = Query(0.0, ge=0, le=1),
    limit: int = Query(50, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> BreachListResponse:
    stmt = select(SanctionsBreach).where(SanctionsBreach.match_confidence >= min_confidence)
    if authorities := _csv(authority):
        stmt = stmt.where(SanctionsBreach.sanctioning_authority.in_([a.upper() for a in authorities]))
    if severities := _csv(severity):
        stmt = stmt.where(SanctionsBreach.severity.in_(severities))
    statuses = _csv(status) or ["flagged", "investigating", "escalated"]
    if statuses != ["all"]:
        stmt = stmt.where(SanctionsBreach.investigation_status.in_(statuses))
    if breach_type:
        stmt = stmt.where(SanctionsBreach.breach_type == breach_type)
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar() or 0
    rows = db.execute(stmt.order_by(SanctionsBreach.match_confidence.desc(), SanctionsBreach.timestamp.desc()).limit(limit).offset(offset)).scalars().all()
    return BreachListResponse(
        total=total,
        filters={"authority": authority, "severity": severity, "status": ",".join(statuses), "breach_type": breach_type, "min_confidence": min_confidence},
        breaches=[BreachOut.model_validate(_breach_view(b)) for b in rows],
    )


@router.get("/breaches/{authority}", response_model=BreachListResponse)
def get_breaches_by_authority(authority: str, limit: int = Query(100, ge=1, le=1000), db: Session = Depends(get_db)) -> BreachListResponse:
    if authority.upper() not in ("OFAC", "EU", "UN"):
        raise HTTPException(status_code=404, detail="Unknown authority")
    return get_breaches(authority=authority.upper(), severity=None, status="all", breach_type=None, min_confidence=0.0, limit=limit, offset=0, db=db)


@router.patch("/breach/{breach_id}", response_model=BreachOut)
def update_breach(breach_id: int, body: InvestigationUpdate, db: Session = Depends(get_db)) -> BreachOut:
    breach = db.get(SanctionsBreach, breach_id)
    if breach is None:
        raise HTTPException(status_code=404, detail="Breach not found")
    changes: dict[str, Any] = {}
    if body.investigation_status and body.investigation_status != breach.investigation_status:
        changes["investigation_status"] = [breach.investigation_status, body.investigation_status]
        breach.investigation_status = body.investigation_status
    if body.analyst_notes is not None:
        changes["analyst_notes"] = body.analyst_notes
        breach.analyst_notes = body.analyst_notes
    if changes:
        action = {"investigating": "investigation_started", "cleared": "cleared", "escalated": "escalated"}.get(body.investigation_status or "", "breach_annotated")
        _audit(db, action, body.updated_by, body.analyst_notes or f"Breach {breach_id} -> {body.investigation_status}", vessel_id=breach.vessel_id, breach_id=breach.id, data={"changes": changes})
        vessel = breach.vessel
        if vessel and body.investigation_status == "cleared":
            remaining = [b for b in vessel.breaches if b.id != breach.id and b.investigation_status not in ("cleared",) and (b.match_confidence or 0) >= 0.6]
            vessel.sanctioned_status = f"breach_{max(remaining, key=lambda b: b.match_confidence or 0).sanctioning_authority.lower()}" if remaining else "clear"
            vessel.risk_score, _ = compute_risk_score(db, vessel)
        db.commit()
        db.refresh(breach)
    return BreachOut.model_validate(_breach_view(breach))


# ------------------------------------------------------------------- evasion
def _evasion_view(e: EvasionEvent, vessel: Vessel | None = None) -> dict[str, Any]:
    v = vessel or e.vessel
    return {**{c.name: getattr(e, c.name) for c in EvasionEvent.__table__.columns}, "vessel_name": v.name if v else None}


@router.get("/evasion-patterns")
def get_evasion_patterns(
    event_type: str | None = Query(None, description="ais_gap, name_change, flag_change, identity_conflict, dark_in_zone, dark_vessel, position_anomaly, spoofing_cluster"),
    severity: str | None = None,
    hours: int = Query(24 * 7, ge=1),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    stmt = select(EvasionEvent).where(EvasionEvent.timestamp >= utcnow() - timedelta(hours=hours))
    if event_type:
        stmt = stmt.where(EvasionEvent.event_type == event_type)
    if severities := _csv(severity):
        stmt = stmt.where(EvasionEvent.severity.in_(severities))
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar() or 0
    rows = db.execute(stmt.order_by(EvasionEvent.timestamp.desc()).limit(limit)).scalars().all()
    by_type = dict(db.execute(select(EvasionEvent.event_type, func.count()).where(EvasionEvent.timestamp >= utcnow() - timedelta(hours=hours)).group_by(EvasionEvent.event_type)).all())
    return jsonable({"total": total, "by_type": by_type, "events": [EvasionOut.model_validate(_evasion_view(e)).model_dump() for e in rows]})


@router.patch("/evasion-patterns/{event_id}")
def update_evasion(event_id: int, body: InvestigationUpdate, db: Session = Depends(get_db)) -> dict[str, Any]:
    event = db.get(EvasionEvent, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Event not found")
    if body.investigation_status:
        event.investigation_status = body.investigation_status
    if body.analyst_notes is not None:
        event.analyst_notes = body.analyst_notes
    _audit(db, "evasion_reviewed", body.updated_by, body.analyst_notes or f"Evasion event {event_id} -> {body.investigation_status}", vessel_id=event.vessel_id, data={"event_type": event.event_type})
    db.commit()
    return jsonable(EvasionOut.model_validate(_evasion_view(event)).model_dump())


# ------------------------------------------------------------- transshipment
def _sts_view(e: TransshipmentEvent) -> TransshipmentOut:
    def mini(v: Vessel | None, mmsi: str | None) -> dict[str, Any]:
        return {"mmsi": v.mmsi if v else mmsi, "name": v.name if v else None, "flag": v.flag_state if v else None, "ship_type": v.ship_type if v else None,
                "sanctioned_status": v.sanctioned_status if v else None, "risk_score": v.risk_score if v else None}
    return TransshipmentOut(
        id=e.id, vessel_a=mini(e.vessel_a, e.vessel_a_mmsi), vessel_b=mini(e.vessel_b, e.vessel_b_mmsi), timestamp=e.timestamp,
        location={"lat": e.location_lat, "lon": e.location_lon}, proximity_meters=e.proximity_meters, duration_minutes=e.duration_minutes,
        confidence_score=e.confidence_score, investigation_status=e.investigation_status, supporting_evidence=e.supporting_evidence, analyst_notes=e.analyst_notes,
    )


@router.get("/transshipment")
def get_transshipments(hours: int = Query(24 * 7, ge=1), min_confidence: float = Query(0.0, ge=0, le=1), limit: int = Query(100, ge=1, le=1000), db: Session = Depends(get_db)) -> dict[str, Any]:
    stmt = select(TransshipmentEvent).where(TransshipmentEvent.timestamp >= utcnow() - timedelta(hours=hours), TransshipmentEvent.confidence_score >= min_confidence)
    rows = db.execute(stmt.order_by(TransshipmentEvent.confidence_score.desc(), TransshipmentEvent.timestamp.desc()).limit(limit)).scalars().all()
    return jsonable({"total": len(rows), "events": [_sts_view(e).model_dump() for e in rows]})


@router.patch("/transshipment/{event_id}")
def update_transshipment(event_id: int, body: InvestigationUpdate, db: Session = Depends(get_db)) -> dict[str, Any]:
    event = db.get(TransshipmentEvent, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Event not found")
    if body.investigation_status:
        event.investigation_status = body.investigation_status
    if body.analyst_notes is not None:
        event.analyst_notes = body.analyst_notes
    _audit(db, "transshipment_reviewed", body.updated_by, body.analyst_notes or f"Transshipment {event_id} -> {body.investigation_status}", vessel_id=event.vessel_a_id, data={"vessel_b": event.vessel_b_mmsi})
    db.commit()
    return jsonable(_sts_view(event).model_dump())


# --------------------------------------------------------------------- ports
def _port_view(c: PortCallEvent, vessel: Vessel | None = None) -> dict[str, Any]:
    v = vessel or c.vessel
    return {**{col.name: getattr(c, col.name) for col in PortCallEvent.__table__.columns}, "vessel_name": v.name if v else None, "flag": v.flag_state if v else None}


@router.get("/port-calls")
def get_port_calls(
    hours: int = Query(24 * 7, ge=1), port: str | None = None, risk: str | None = Query(None, description="high, medium, safe"),
    only_flagged: bool = False, open_only: bool = False, limit: int = Query(200, ge=1, le=2000), db: Session = Depends(get_db),
) -> dict[str, Any]:
    stmt = select(PortCallEvent).where(PortCallEvent.arrival_time >= utcnow() - timedelta(hours=hours))
    if port:
        stmt = stmt.where(PortCallEvent.port_name.ilike(f"%{port}%"))
    if risk:
        stmt = stmt.where(PortCallEvent.facility_risk_level == risk)
    if only_flagged:
        stmt = stmt.where(or_(PortCallEvent.is_sanctioned_facility.is_(True), PortCallEvent.facility_risk_level == "high"))
    if open_only:
        stmt = stmt.where(PortCallEvent.departure_time.is_(None))
    rows = db.execute(stmt.order_by(PortCallEvent.arrival_time.desc()).limit(limit)).scalars().all()
    by_port = db.execute(
        select(PortCallEvent.port_name, PortCallEvent.facility_risk_level, func.count()).where(PortCallEvent.arrival_time >= utcnow() - timedelta(hours=hours)).group_by(PortCallEvent.port_name, PortCallEvent.facility_risk_level).order_by(func.count().desc())
    ).all()
    return jsonable({"total": len(rows), "by_port": [{"port": p, "risk_level": r, "calls": n} for p, r, n in by_port[:40]], "calls": [PortCallOut.model_validate(_port_view(c)).model_dump() for c in rows]})


@router.get("/port-calls/{timerange}")
def get_port_calls_range(timerange: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Alias: ``24h``, ``7d``, ``30d``."""
    unit = timerange[-1]
    try:
        amount = int(timerange[:-1])
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="timerange like 24h or 7d") from exc
    hours = amount * (24 if unit == "d" else 1)
    return get_port_calls(hours=hours, port=None, risk=None, only_flagged=False, open_only=False, limit=500, db=db)


@router.get("/ports")
def get_ports() -> dict[str, Any]:
    return {"type": "FeatureCollection", "features": [{"type": "Feature", "geometry": {"type": "Point", "coordinates": [p["lon"], p["lat"]]}, "properties": {k: v for k, v in p.items() if k not in ("lat", "lon")}} for p in PORTS]}


# ---------------------------------------------------------- lanes and zones
def _lane_view(violation: ShippingLaneViolation, vessel: Vessel | None = None) -> dict[str, Any]:
    return {**{c.name: getattr(violation, c.name) for c in ShippingLaneViolation.__table__.columns}, "vessel_name": vessel.name if vessel else None}


@router.get("/shipping-lanes")
def get_shipping_lanes() -> dict[str, Any]:
    return {"lanes": lanes_geojson()}


@router.get("/sanctions-zones")
def get_sanctions_zones() -> dict[str, Any]:
    """Zones grouped by authority (a zone can appear under several) plus war/piracy zones."""
    geojson = zones_geojson()
    grouped: dict[str, list] = {"ofac": [], "eu": [], "un": [], "other": []}
    for feature in geojson["features"]:
        authorities = [a.lower() for a in feature["properties"]["authorities"]]
        if not authorities:
            grouped["other"].append(feature)
        for authority in authorities:
            grouped.setdefault(authority, []).append(feature)
    return {key: {"type": "FeatureCollection", "features": features} for key, features in grouped.items()} | {"all": geojson}


@router.get("/shipping-lanes/violations")
def get_lane_violations(hours: int = Query(24 * 7, ge=1), context: str | None = None, limit: int = Query(200, ge=1, le=2000), db: Session = Depends(get_db)) -> dict[str, Any]:
    stmt = select(ShippingLaneViolation, Vessel).join(Vessel, Vessel.id == ShippingLaneViolation.vessel_id).where(ShippingLaneViolation.timestamp >= utcnow() - timedelta(hours=hours))
    if context:
        stmt = stmt.where(ShippingLaneViolation.context == context)
    rows = db.execute(stmt.order_by(ShippingLaneViolation.timestamp.desc()).limit(limit)).all()
    by_lane = dict(db.execute(select(ShippingLaneViolation.lane_name, func.count()).where(ShippingLaneViolation.timestamp >= utcnow() - timedelta(hours=hours)).group_by(ShippingLaneViolation.lane_name)).all())
    return jsonable({"total": len(rows), "by_lane": by_lane, "violations": [LaneViolationOut.model_validate(_lane_view(violation, v)).model_dump() for violation, v in rows]})


# ------------------------------------------------------------------ audit log
def _audit_query(db: Session, start_date, end_date, action_type, vessel_id, user):
    stmt = select(AuditLog)
    if start_date:
        stmt = stmt.where(AuditLog.timestamp >= start_date)
    if end_date:
        stmt = stmt.where(AuditLog.timestamp <= end_date)
    if action_type:
        stmt = stmt.where(AuditLog.action_type.in_(_csv(action_type)))
    if vessel_id:
        stmt = stmt.where(AuditLog.vessel_id == vessel_id)
    if user:
        stmt = stmt.where(AuditLog.user_id == user)
    return stmt


@router.get("/audit-log", response_model=AuditLogResponse)
def get_audit_log(
    start_date: str | None = None, end_date: str | None = None, action_type: str | None = None, vessel_id: int | None = None, user: str | None = None,
    limit: int = Query(100, ge=1, le=2000), offset: int = Query(0, ge=0), db: Session = Depends(get_db),
) -> AuditLogResponse:
    stmt = _audit_query(db, start_date, end_date, action_type, vessel_id, user)
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar() or 0
    rows = db.execute(stmt.order_by(AuditLog.timestamp.desc(), AuditLog.id.desc()).limit(limit).offset(offset)).scalars().all()
    return AuditLogResponse(total=total, limit=limit, offset=offset, entries=[AuditEntryOut.model_validate(a) for a in rows])


@router.get("/audit-log/actions")
def get_audit_actions(db: Session = Depends(get_db)) -> dict[str, int]:
    return dict(db.execute(select(AuditLog.action_type, func.count()).group_by(AuditLog.action_type).order_by(func.count().desc())).all())


@router.post("/audit-log/export")
def export_audit_log(body: ExportRequest, db: Session = Depends(get_db)):
    """Export the audit trail (JSON / CSV now; PDF intelligence report in Phase 4)."""
    stmt = _audit_query(db, body.start_date, body.end_date, body.action_type, body.vessel_id, None)
    rows = db.execute(stmt.order_by(AuditLog.timestamp.desc()).limit(10000)).scalars().all()
    _audit(db, "export", body.requested_by, f"Audit log exported as {body.format} ({len(rows)} entries)", data={"format": body.format, "classification": body.classification, "entries": len(rows)})
    db.commit()
    stamp = utcnow().strftime("%Y-%m-%d")
    if body.format == "csv":
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(["id", "timestamp", "action_type", "user", "vessel_id", "breach_id", "sanctioned_entity", "authorities", "rationale", "classification"])
        for a in rows:
            writer.writerow([a.id, to_iso_z(a.timestamp), a.action_type, a.user_id, a.vessel_id, a.breach_id, a.sanctioned_entity_name, ";".join(a.sanctioning_authorities or []), a.rationale, a.classification_level])
        return Response(buffer.getvalue(), media_type="text/csv", headers={"Content-Disposition": f"attachment; filename=VELES_Audit_Log_{stamp}.csv"})
    if body.format == "pdf":
        start = body.start_date or (utcnow() - timedelta(days=14))
        end = body.end_date or utcnow()
        report, _ = maritime_report(db, start, end, body.include_sections, body.classification, body.vessel_id)
        return Response(build_pdf(report), media_type="application/pdf", headers={"Content-Disposition": f"attachment; filename=VELES_Intelligence_Report_{stamp}.pdf"})
    payload = {
        "classification": body.classification, "generated_at": utcnow(), "period": {"start": body.start_date, "end": body.end_date},
        "sections": body.include_sections, "total": len(rows), "entries": [AuditEntryOut.model_validate(a).model_dump() for a in rows],
    }
    return Response(json.dumps(jsonable(payload), default=str, indent=2), media_type="application/json", headers={"Content-Disposition": f"attachment; filename=VELES_Audit_Log_{stamp}.json"})


@router.get("/report")
def maritime_intelligence_report(
    days: int = Query(7, ge=1, le=365), format: Literal["json", "pdf"] = "json", classification: str = Query("UNCLASSIFIED", max_length=50),
    sections: str | None = Query(None, description="Comma-separated subset of: executive_summary,breach_analysis,vessel_profiles,evasion,transshipment,port_activity,zone_activity,audit_entries,recommendations"),
    db: Session = Depends(get_db),
):
    """Maritime intelligence report for the last ``days`` (JSON or PDF), audited as an export."""
    end = utcnow()
    start = end - timedelta(days=days)
    report, data = maritime_report(db, start, end, _csv(sections) or None, classification)
    _audit(db, "export", "anonymous", f"Maritime intelligence report ({format}, {days} d)", data={"format": format, "classification": classification, "days": days})
    db.commit()
    if format == "pdf":
        return Response(build_pdf(report), media_type="application/pdf", headers={"Content-Disposition": f"attachment; filename=VELES_Maritime_Report_{end:%Y-%m-%d}.pdf"})
    return jsonable(data)


# -------------------------------------------------------------------- status
@router.get("/status")
def get_status() -> dict[str, Any]:
    from app.bots.maritime import maritime_bot

    return jsonable(maritime_bot.status())


@router.get("/vessel/{mmsi}/dossier")
def vessel_dossier(mmsi: str, format: str = Query("json", pattern="^(json|pdf)$"), classification: str = Query("UNCLASSIFIED", max_length=50), db: Session = Depends(get_db)):
    """Cross-domain context for one hull: port state control, energy shipments, dark-oil indicators, fusion links, listed owner (JSON or PDF)."""
    from app.models.correlation import SignalCorrelation
    from app.models.energy import DarkOilIndicator, OilTankerShipment
    from app.models.sanctions import SanctionsEntity
    from app.models.tier2 import PscEvent

    vessel = _vessel_or_404(db, mmsi)
    psc = db.execute(select(PscEvent).where(or_(PscEvent.vessel_id == vessel.id, PscEvent.imo == vessel.imo) if vessel.imo else PscEvent.vessel_id == vessel.id).order_by(PscEvent.event_date.desc().nulls_last()).limit(30)).scalars().all()
    shipments = db.execute(select(OilTankerShipment).where(OilTankerShipment.vessel_id == vessel.id).order_by(OilTankerShipment.loading_date.desc()).limit(30)).scalars().all()
    dark = db.execute(select(DarkOilIndicator).where(DarkOilIndicator.tanker_id == vessel.id).order_by(DarkOilIndicator.detected_at.desc()).limit(30)).scalars().all()
    # fusion links: any correlation whose stored summaries name this vessel (summaries carry the name / MMSI)
    needle = f"%{vessel.name}%" if vessel.name and len(vessel.name) >= 5 else f"%{vessel.mmsi}%"
    links = db.execute(
        select(SignalCorrelation).where(or_(SignalCorrelation.signal_a_summary.ilike(needle), SignalCorrelation.signal_b_summary.ilike(needle), SignalCorrelation.signal_a_summary.ilike(f"%{vessel.mmsi}%"), SignalCorrelation.signal_b_summary.ilike(f"%{vessel.mmsi}%")))
        .order_by(SignalCorrelation.confidence.desc()).limit(40)
    ).scalars().all()
    clusters = db.execute(
        select(EvasionEvent).where(EvasionEvent.event_type == "spoofing_cluster", cast(EvasionEvent.details, String).contains(f'"mmsi": "{vessel.mmsi}"')).order_by(EvasionEvent.timestamp.desc()).limit(20)
    ).scalars().all()
    listed: list[dict[str, Any]] = []
    if vessel.imo:
        for entity in db.execute(select(SanctionsEntity).where(SanctionsEntity.imo == vessel.imo, SanctionsEntity.is_active.is_(True))).scalars():
            listed.append({"id": entity.id, "authority": entity.designating_authority, "name": entity.name, "programs": entity.programs, "designation_date": entity.designation_date, "vessel_owner": entity.vessel_owner, "vessel_flag": entity.vessel_flag})
    payload = jsonable(
        {
            "vessel": {"id": vessel.id, "mmsi": vessel.mmsi, "imo": vessel.imo, "name": vessel.name, "flag": vessel.flag_state, "ship_type": vessel.ship_type, "length_m": vessel.length_m, "draught": vessel.draught},
            "listings_by_imo": listed,
            "port_state_control": [{"id": p.id, "source": p.source, "event_type": p.event_type, "port": p.port, "port_country": p.port_country, "event_date": p.event_date, "release_date": p.release_date, "deficiency_count": p.deficiency_count,
                                    "deficiencies": (p.deficiencies or [])[:10], "company": p.company, "class_society": p.class_society, "details": p.details} for p in psc],
            "shipments": [{"id": s.id, "loading_location": s.loading_location, "origin_country": s.origin_country, "loading_date": s.loading_date, "discharge_location": s.discharge_location, "destination_country": s.destination_country, "discharge_date": s.discharge_date,
                           "cargo_type": s.cargo_type, "cargo_volume_barrels": s.cargo_volume_barrels, "laden": s.laden, "sanctioned_route": s.sanctioned_route, "dark_oil_suspect": s.dark_oil_suspect, "status": s.status, "risk_score": s.risk_score} for s in shipments],
            "dark_oil_indicators": [{"id": d.id, "pattern": d.detected_pattern, "severity": d.severity, "confidence": d.confidence_score, "summary": d.summary, "detected_at": d.detected_at, "status": d.investigation_status} for d in dark],
            "fusion_links": [{"id": c.id, "type": c.correlation_type, "confidence": c.confidence, "a": c.signal_a_summary, "b": c.signal_b_summary, "shared_keys": c.shared_keys, "detected_at": c.detected_at} for c in links],
            "spoofing_clusters": [{"id": e.id, "timestamp": e.timestamp, "severity": e.severity, "summary": e.summary, "vessel_count": (e.details or {}).get("vessel_count"), "inland": (e.details or {}).get("inland"), "zones": (e.details or {}).get("zones")} for e in clusters],
        }
    )
    if format == "pdf":
        from app.reports.dossier import vessel_dossier_report
        from app.reports.pdf import build_pdf

        db.add(AuditLog(action_type="export", user_id="analyst", vessel_id=vessel.id, rationale=f"vessel dossier PDF for {vessel.name} ({vessel.mmsi})", source_systems=["api.maritime"], created_by="analyst"))
        db.commit()
        return Response(build_pdf(vessel_dossier_report(payload, classification)), media_type="application/pdf", headers={"Content-Disposition": f"attachment; filename=VELES_Vessel_{vessel.mmsi}_{utcnow():%Y-%m-%d}.pdf"})
    return payload
