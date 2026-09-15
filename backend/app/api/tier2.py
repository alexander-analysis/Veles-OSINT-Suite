"""Tier 2 / 3 routers: /api/aviation, /api/leaks, /api/narratives, /api/infra, /api/legal."""

from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.bots.aviation import aviation_bot
from app.bots.infra import infra_bot
from app.bots.leaks import leaks_bot
from app.bots.legal import legal_bot
from app.bots.narratives import narrative_bot
from app.bots.runtime import bot_loop
from app.database import get_db
from app.models.audit import AuditLog
from app.models.tier2 import Aircraft, AircraftSighting, BreachEvent, InfraAsset, LegalEvent, Narrative
from app.schemas.common import APIModel
from app.utils.serialization import jsonable
from app.utils.time import utcnow

aviation = APIRouter(tags=["aviation"])
leaks = APIRouter(tags=["leaks"])
narratives = APIRouter(tags=["narratives"])
infra = APIRouter(tags=["infra"])
legal = APIRouter(tags=["legal"])


# ------------------------------------------------------------------ schemas
class AircraftOut(APIModel):
    id: int
    registration: str
    icao_hex: str | None = None
    model: str | None = None
    operator: str | None = None
    owner: str | None = None
    manufacturer_serial: str | None = None
    country: str | None = None
    is_sanctioned: bool = False
    sanctioned_entity_id: int | None = None
    sanctioning_authority: str | None = None
    programs: list[str] | None = None
    watch: bool = True
    origin: str | None = None
    notes: str | None = None
    last_seen: datetime | None = None
    last_lat: float | None = None
    last_lon: float | None = None
    last_altitude_ft: float | None = None
    last_callsign: str | None = None
    last_checked: datetime | None = None
    sightings_count: int | None = None


class SightingOut(APIModel):
    id: int
    aircraft_id: int
    registration: str | None = None
    icao_hex: str | None = None
    timestamp: datetime
    latitude: float | None = None
    longitude: float | None = None
    altitude_ft: float | None = None
    ground_speed_kts: float | None = None
    heading: float | None = None
    callsign: str | None = None
    squawk: str | None = None
    on_ground: bool | None = None
    source: str | None = None
    nearest_place: str | None = None
    flight_key: str | None = None


class AddAircraftRequest(APIModel):
    registration: str
    icao_hex: str | None = None
    operator: str | None = None
    model: str | None = None
    notes: str | None = None
    analyst: str | None = None


class BreachOut(APIModel):
    id: int
    source: str
    victim_name: str
    victim_domain: str | None = None
    country: str | None = None
    sector: str | None = None
    threat_actor: str | None = None
    event_date: datetime | None = None
    discovered_at: datetime
    description: str | None = None
    url: str | None = None
    records_affected: int | None = None
    data_classes: list[str] | None = None
    matched_company_id: int | None = None
    matched_entity_id: int | None = None
    relevance: str | None = None
    relevance_score: float | None = None
    severity: str | None = None
    details: dict[str, Any] | None = None


class NarrativeOut(APIModel):
    id: int
    topic: str
    keywords: list[str] | None = None
    outlets: dict[str, int] | None = None
    outlet_count: int | None = None
    item_count: int | None = None
    countries: list[str] | None = None
    sample_titles: list[str] | None = None
    sample_urls: list[str] | None = None
    first_seen: datetime | None = None
    last_seen: datetime | None = None
    western_coverage: int | None = None
    divergence: str | None = None
    score: float | None = None
    severity: str | None = None
    assessment: str | None = None
    detected_at: datetime


class InfraOut(APIModel):
    id: int
    asset_type: str
    value: str
    entity_id: int | None = None
    entity_name: str | None = None
    company_id: int | None = None
    registrar: str | None = None
    registered_at: datetime | None = None
    expires_at: datetime | None = None
    nameservers: list[str] | None = None
    resolves_to: list[str] | None = None
    asn: str | None = None
    asn_org: str | None = None
    hosting_country: str | None = None
    certificate_count: int | None = None
    certificate_names: list[str] | None = None
    is_live: bool | None = None
    findings: list[str] | None = None
    risk_score: float | None = None
    last_checked: datetime | None = None


class LegalOut(APIModel):
    id: int
    source: str
    title: str
    url: str | None = None
    court: str | None = None
    event_date: datetime | None = None
    discovered_at: datetime
    event_type: str | None = None
    matched_entity_id: int | None = None
    matched_entity_name: str | None = None
    query_used: str | None = None
    summary: str | None = None
    penalty_usd: float | None = None
    relevance_score: float | None = None
    details: dict[str, Any] | None = None


# ----------------------------------------------------------------- aviation
@aviation.get("/aircraft", response_model=list[AircraftOut])
def list_aircraft(seen_days: int | None = Query(None, ge=1), operator: str | None = None, country: str | None = None, q: str | None = Query(None, max_length=60), limit: int = Query(200, ge=1, le=1000), db: Session = Depends(get_db)) -> list[AircraftOut]:
    query = select(Aircraft)
    if seen_days:
        query = query.where(Aircraft.last_seen >= utcnow() - timedelta(days=seen_days))
    if operator:
        query = query.where(Aircraft.operator.ilike(f"%{operator}%"))
    if country:
        query = query.where(Aircraft.country == country.upper())
    if q:
        query = query.where(or_(Aircraft.registration.ilike(f"%{q}%"), Aircraft.icao_hex.ilike(f"%{q}%"), Aircraft.model.ilike(f"%{q}%"), Aircraft.operator.ilike(f"%{q}%")))
    rows = db.execute(query.order_by(Aircraft.last_seen.desc().nulls_last(), Aircraft.registration).limit(limit)).scalars().all()
    return [AircraftOut.model_validate(r) for r in rows]


@aviation.get("/aircraft/{aircraft_id}/sightings", response_model=list[SightingOut])
def aircraft_sightings(aircraft_id: int, days: int = Query(30, ge=1, le=365), limit: int = Query(500, ge=1, le=5000), db: Session = Depends(get_db)) -> list[SightingOut]:
    if db.get(Aircraft, aircraft_id) is None:
        raise HTTPException(status_code=404, detail="Aircraft not found")
    rows = db.execute(select(AircraftSighting).where(AircraftSighting.aircraft_id == aircraft_id, AircraftSighting.timestamp >= utcnow() - timedelta(days=days)).order_by(AircraftSighting.timestamp.desc()).limit(limit)).scalars().all()
    return [SightingOut.model_validate(r) for r in rows]


@aviation.get("/sightings", response_model=list[SightingOut])
def recent_sightings(hours: int = Query(48, ge=1, le=24 * 30), limit: int = Query(300, ge=1, le=2000), db: Session = Depends(get_db)) -> list[SightingOut]:
    rows = db.execute(select(AircraftSighting).where(AircraftSighting.timestamp >= utcnow() - timedelta(hours=hours)).order_by(AircraftSighting.timestamp.desc()).limit(limit)).scalars().all()
    return [SightingOut.model_validate(r) for r in rows]


@aviation.get("/geojson")
def aviation_geojson(hours: int = Query(48, ge=1, le=24 * 30), db: Session = Depends(get_db)) -> dict[str, Any]:
    rows = db.execute(select(Aircraft).where(Aircraft.last_seen >= utcnow() - timedelta(hours=hours), Aircraft.last_lat.is_not(None))).scalars().all()
    return {"type": "FeatureCollection", "features": [{"type": "Feature", "geometry": {"type": "Point", "coordinates": [a.last_lon, a.last_lat]},
                                                       "properties": jsonable({"id": a.id, "registration": a.registration, "operator": a.operator, "model": a.model, "callsign": a.last_callsign, "altitude_ft": a.last_altitude_ft, "last_seen": a.last_seen, "sanctioned": a.is_sanctioned})} for a in rows]}


@aviation.post("/aircraft", response_model=AircraftOut, status_code=201)
def add_aircraft(body: AddAircraftRequest, db: Session = Depends(get_db)) -> AircraftOut:
    registration = body.registration.strip().upper()
    row = db.execute(select(Aircraft).where(Aircraft.registration == registration)).scalar_one_or_none()
    if row is None:
        row = Aircraft(registration=registration, origin="analyst", created_at=utcnow())
        db.add(row)
    row.icao_hex = (body.icao_hex or row.icao_hex or "").lower() or None
    row.operator = body.operator or row.operator
    row.model = body.model or row.model
    row.notes = body.notes or row.notes
    row.watch = True
    db.add(AuditLog(action_type="aircraft_watch_added", user_id=body.analyst or "analyst", rationale=body.notes or f"Watch aircraft {registration}", supporting_data={"registration": registration}, source_systems=["api.aviation"], created_by=body.analyst or "analyst"))
    db.commit()
    db.refresh(row)
    return AircraftOut.model_validate(row)


@aviation.get("/summary")
def aviation_summary(days: int = Query(7, ge=1, le=90), db: Session = Depends(get_db)) -> dict[str, Any]:
    return jsonable(aviation_bot.summary(db, days))


@aviation.get("/status")
def aviation_status() -> dict[str, Any]:
    return jsonable(aviation_bot.status())


@aviation.post("/refresh", status_code=202)
def aviation_refresh(job: str = Query("all", pattern="^(all|sync|sweep|hexes)$")) -> dict[str, Any]:
    jobs = {"sync": aviation_bot.sync_aircraft, "sweep": aviation_bot.sweep, "hexes": aviation_bot.poll_hexes}
    selected = list(jobs) if job == "all" else [job]
    for name in selected:
        bot_loop.submit(jobs[name]())
    return {"status": "started", "jobs": selected}


# -------------------------------------------------------------------- leaks
@leaks.get("/events", response_model=list[BreachOut])
def list_breaches(days: int = Query(30, ge=1, le=365), relevance: str | None = None, min_score: float = Query(0.0, ge=0, le=1), source: str | None = None, q: str | None = Query(None, max_length=100), limit: int = Query(200, ge=1, le=1000), db: Session = Depends(get_db)) -> list[BreachOut]:
    query = select(BreachEvent).where(BreachEvent.discovered_at >= utcnow() - timedelta(days=days), BreachEvent.relevance_score >= min_score)
    if relevance:
        query = query.where(BreachEvent.relevance == relevance)
    if source:
        query = query.where(BreachEvent.source == source)
    if q:
        query = query.where(or_(BreachEvent.victim_name.ilike(f"%{q}%"), BreachEvent.victim_domain.ilike(f"%{q}%"), BreachEvent.threat_actor.ilike(f"%{q}%")))
    rows = db.execute(query.order_by(BreachEvent.relevance_score.desc(), BreachEvent.discovered_at.desc()).limit(limit)).scalars().all()
    return [BreachOut.model_validate(r) for r in rows]


@leaks.get("/summary")
def leaks_summary(days: int = Query(30, ge=1, le=365), db: Session = Depends(get_db)) -> dict[str, Any]:
    return jsonable(leaks_bot.summary(db, days))


@leaks.get("/status")
def leaks_status() -> dict[str, Any]:
    return jsonable(leaks_bot.status())


@leaks.post("/refresh", status_code=202)
def leaks_refresh() -> dict[str, Any]:
    bot_loop.submit(leaks_bot.fetch())
    return {"status": "started"}


# --------------------------------------------------------------- narratives
@narratives.get("/", response_model=list[NarrativeOut])
def list_narratives(days: int = Query(7, ge=1, le=90), divergence: str | None = None, min_score: float = Query(0.0, ge=0, le=1), limit: int = Query(100, ge=1, le=500), db: Session = Depends(get_db)) -> list[NarrativeOut]:
    query = select(Narrative).where(Narrative.last_seen >= utcnow() - timedelta(days=days), Narrative.score >= min_score)
    if divergence:
        query = query.where(Narrative.divergence == divergence)
    rows = db.execute(query.order_by(Narrative.score.desc(), Narrative.last_seen.desc()).limit(limit)).scalars().all()
    return [NarrativeOut.model_validate(r) for r in rows]


@narratives.get("/summary")
def narratives_summary(days: int = Query(7, ge=1, le=90), db: Session = Depends(get_db)) -> dict[str, Any]:
    return jsonable(narrative_bot.summary(db, days))


@narratives.get("/status")
def narratives_status() -> dict[str, Any]:
    return jsonable(narrative_bot.status())


@narratives.post("/refresh", status_code=202)
def narratives_refresh() -> dict[str, Any]:
    bot_loop.submit(narrative_bot.run())
    return {"status": "started"}


# -------------------------------------------------------------------- infra
@infra.get("/assets", response_model=list[InfraOut])
def list_assets(live: bool | None = None, country: str | None = None, q: str | None = Query(None, max_length=120), checked: bool | None = None, min_risk: float = Query(0.0, ge=0, le=1), limit: int = Query(200, ge=1, le=2000), db: Session = Depends(get_db)) -> list[InfraOut]:
    query = select(InfraAsset)
    if live is not None:
        query = query.where(InfraAsset.is_live.is_(live))
    if country:
        query = query.where(InfraAsset.hosting_country == country.upper())
    if q:
        query = query.where(or_(InfraAsset.value.ilike(f"%{q}%"), InfraAsset.entity_name.ilike(f"%{q}%"), InfraAsset.asn_org.ilike(f"%{q}%")))
    if checked is True:
        query = query.where(InfraAsset.last_checked.is_not(None))
    elif checked is False:
        query = query.where(InfraAsset.last_checked.is_(None))
    if min_risk:
        query = query.where(InfraAsset.risk_score >= min_risk)
    rows = db.execute(query.order_by(InfraAsset.risk_score.desc().nulls_last(), InfraAsset.value).limit(limit)).scalars().all()
    return [InfraOut.model_validate(r) for r in rows]


@infra.get("/summary")
def infra_summary(db: Session = Depends(get_db)) -> dict[str, Any]:
    return jsonable(infra_bot.summary(db))


@infra.get("/status")
def infra_status() -> dict[str, Any]:
    return jsonable(infra_bot.status())


@infra.post("/refresh", status_code=202)
def infra_refresh(job: str = Query("all", pattern="^(all|seed|footprint)$")) -> dict[str, Any]:
    jobs = {"seed": infra_bot.seed, "footprint": infra_bot.footprint}
    selected = list(jobs) if job == "all" else [job]
    for name in selected:
        bot_loop.submit(jobs[name]())
    return {"status": "started", "jobs": selected}


# -------------------------------------------------------------------- legal
@legal.get("/events", response_model=list[LegalOut])
def list_legal(days: int = Query(90, ge=1, le=3650), source: str | None = None, event_type: str | None = None, matched_only: bool = False, q: str | None = Query(None, max_length=120), limit: int = Query(200, ge=1, le=1000), db: Session = Depends(get_db)) -> list[LegalOut]:
    since = utcnow() - timedelta(days=days)
    query = select(LegalEvent).where(or_(LegalEvent.event_date >= since, LegalEvent.discovered_at >= since))
    if source:
        query = query.where(LegalEvent.source == source)
    if event_type:
        query = query.where(LegalEvent.event_type == event_type)
    if matched_only:
        query = query.where(LegalEvent.matched_entity_id.is_not(None))
    if q:
        query = query.where(or_(LegalEvent.title.ilike(f"%{q}%"), LegalEvent.matched_entity_name.ilike(f"%{q}%"), LegalEvent.summary.ilike(f"%{q}%")))
    rows = db.execute(query.order_by(LegalEvent.event_date.desc().nulls_last(), LegalEvent.discovered_at.desc()).limit(limit)).scalars().all()
    return [LegalOut.model_validate(r) for r in rows]


@legal.get("/summary")
def legal_summary(days: int = Query(90, ge=1, le=3650), db: Session = Depends(get_db)) -> dict[str, Any]:
    out = legal_bot.summary(db, days)
    out["stored_total"] = db.execute(select(func.count(LegalEvent.id))).scalar() or 0
    return jsonable(out)


@legal.get("/status")
def legal_status() -> dict[str, Any]:
    return jsonable(legal_bot.status())


@legal.post("/refresh", status_code=202)
def legal_refresh(job: str = Query("all", pattern="^(all|official|dockets)$")) -> dict[str, Any]:
    jobs = {"official": legal_bot.fetch_official, "dockets": legal_bot.search_dockets}
    selected = list(jobs) if job == "all" else [job]
    for name in selected:
        bot_loop.submit(jobs[name]())
    return {"status": "started", "jobs": selected}
