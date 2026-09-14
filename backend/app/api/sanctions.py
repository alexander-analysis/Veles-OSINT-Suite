"""/api/sanctions/* - sanctions database search, screening, updates and programmes."""

import re
from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import String, func, or_, select
from sqlalchemy.orm import Session

from app.analysis.sanctions import Match
from app.bots.runtime import bot_loop
from app.bots.sanctions import sanctions_bot
from app.database import get_db
from app.integrations.sanctions_common import normalize_name
from app.models.audit import AuditLog
from app.models.maritime import SanctionsBreach, Vessel
from app.models.sanctions import SanctionsEntity, SanctionsProgramTracking, SanctionsUpdate
from app.schemas.sanctions import (
    CheckEntityRequest,
    CheckEntityResponse,
    EntitySearchResponse,
    MatchOut,
    ProgramOut,
    ProgramsResponse,
    SanctionsEntityOut,
    SanctionsUpdateOut,
    UpdatesResponse,
    VesselSanctionsResponse,
)
from app.utils.serialization import jsonable
from app.utils.time import utcnow

router = APIRouter(tags=["sanctions"])


def _csv(value: str | None) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()] if value else []


def match_out(match: Match) -> MatchOut:
    entity = match.entity
    return MatchOut(
        authority=match.authority,
        entity_id=entity.id if entity else None,
        official_name=entity.name if entity else None,
        entity_type=entity.entity_type if entity else None,
        match_type=match.match_type,
        matched_value=match.matched_value,
        similarity=match.similarity,
        confidence=match.confidence,
        severity=match.severity,
        breach_type=match.breach_type,
        programs=list(match.programs or []),
        designation_date=entity.designation_date if entity else None,
        summary=match.summary,
    )


def _with_authorities(db: Session, rows: list[SanctionsEntity]) -> list[SanctionsEntityOut]:
    """Attach the set of authorities that actively list the same normalised name."""
    names = {r.name_normalized for r in rows if r.name_normalized}
    grouped: dict[str, set[str]] = {}
    if names:
        for name, authority in db.execute(
            select(SanctionsEntity.name_normalized, SanctionsEntity.designating_authority)
            .where(SanctionsEntity.name_normalized.in_(names), SanctionsEntity.is_active.is_(True))
            .distinct()
        ):
            grouped.setdefault(name, set()).add(authority)
    out = []
    for row in rows:
        item = SanctionsEntityOut.model_validate(row)
        item.designating_authorities = sorted(grouped.get(row.name_normalized, {row.designating_authority}))
        out.append(item)
    return out


@router.get("/entities", response_model=EntitySearchResponse)
def search_entities(
    query: str | None = Query(None, min_length=2, description="Name, alias fragment, IMO or MMSI"),
    type: str | None = Query(None, description="vessel, company, person, aircraft"),
    authority: str | None = Query(None, description="Comma-separated: OFAC,EU,UN"),
    program: str | None = Query(None, description="Programme substring, e.g. RUSSIA"),
    active: bool = True,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> EntitySearchResponse:
    stmt = select(SanctionsEntity)
    if active:
        stmt = stmt.where(SanctionsEntity.is_active.is_(True))
    if type:
        stmt = stmt.where(SanctionsEntity.entity_type == type)
    if authorities := _csv(authority):
        stmt = stmt.where(SanctionsEntity.designating_authority.in_([a.upper() for a in authorities]))
    if program:
        stmt = stmt.where(func.upper(func.cast(SanctionsEntity.programs, String)).like(f"%{program.upper()}%"))
    if query:
        q = query.strip()
        if re.fullmatch(r"\d{7}", q):
            stmt = stmt.where(SanctionsEntity.imo == q)
        elif re.fullmatch(r"\d{9}", q):
            stmt = stmt.where(SanctionsEntity.mmsi == q)
        else:
            normalized = normalize_name(q)
            stmt = stmt.where(
                or_(
                    SanctionsEntity.name_normalized.like(f"%{normalized}%"),
                    func.upper(func.cast(SanctionsEntity.aliases, String)).like(f"%{q.upper()}%"),
                )
            )
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar() or 0
    rows = db.execute(stmt.order_by(SanctionsEntity.name).limit(limit).offset(offset)).scalars().all()
    return EntitySearchResponse(
        query=query,
        filters={"type": type, "authorities": _csv(authority), "program": program, "active": active},
        total=total,
        limit=limit,
        offset=offset,
        entities=_with_authorities(db, rows),
    )


@router.get("/entities/{entity_id}", response_model=SanctionsEntityOut)
def get_entity(entity_id: int, db: Session = Depends(get_db)) -> SanctionsEntityOut:
    row = db.get(SanctionsEntity, entity_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Entity not found")
    return _with_authorities(db, [row])[0]


@router.post("/check-entity", response_model=CheckEntityResponse)
def check_entity(body: CheckEntityRequest, db: Session = Depends(get_db)) -> CheckEntityResponse:
    """Screen a name against every list (audited as a sanctions check)."""
    matches = sanctions_bot.check_entity(body.entity_name, body.entity_type, body.min_similarity)
    if not body.check_aliases:
        matches = [m for m in matches if m.similarity == 1.0 and m.entity and normalize_name(m.entity.name) == normalize_name(body.entity_name)]
    confidence = max((m.confidence for m in matches), default=0.0)
    authorities = sorted({m.authority for m in matches})
    programs = sorted({p for m in matches for p in m.programs})
    db.add(
        AuditLog(
            action_type="sanctions_check",
            user_id=body.requested_by,
            sanctioning_authorities=["OFAC", "EU", "UN"],
            sanctioned_entity_name=matches[0].entity.name if matches and matches[0].entity else None,
            rationale=f"Entity check for '{body.entity_name}': {'match' if matches else 'no match'} (confidence {confidence:.2f})",
            supporting_data={"entity_name": body.entity_name, "entity_type": body.entity_type, "matches": len(matches), "authorities": authorities},
            source_systems=["api.sanctions"],
            created_by=body.requested_by,
        )
    )
    db.commit()
    return CheckEntityResponse(
        entity_name=body.entity_name,
        is_sanctioned=confidence >= 0.85,
        confidence=confidence,
        designating_authorities=authorities,
        sanctions_programs=programs,
        matching_entries=[match_out(m) for m in matches],
    )


@router.get("/vessel/{mmsi}", response_model=VesselSanctionsResponse)
def vessel_sanctions(mmsi: str, db: Session = Depends(get_db)) -> VesselSanctionsResponse:
    """Recorded breaches plus a live screen of the vessel's current identity."""
    vessel = db.execute(select(Vessel).where(Vessel.mmsi == mmsi)).scalar_one_or_none()
    if vessel is None:
        raise HTTPException(status_code=404, detail="Vessel not tracked")
    matches = sanctions_bot.check_vessel(vessel)
    breaches = db.execute(select(SanctionsBreach).where(SanctionsBreach.vessel_id == vessel.id).order_by(SanctionsBreach.timestamp.desc())).scalars().all()
    programs = sorted({p for m in matches for p in m.programs})
    top = max((m.confidence for m in matches), default=0.0)
    if top >= 0.9:
        recommendation = "Alert - vessel or its owner is a designated entity; escalate for investigation"
    elif top >= 0.6:
        recommendation = "Review - strong indicator; verify identity (IMO, ownership) before action"
    elif matches:
        recommendation = "Monitor - low-confidence match in the review queue"
    else:
        recommendation = "Clear - no listing matched the vessel's current identity"
    return VesselSanctionsResponse(
        mmsi=vessel.mmsi,
        vessel_name=vessel.name,
        imo=vessel.imo,
        flag=vessel.flag_state,
        owner=vessel.owner_name,
        sanctions_status=vessel.sanctioned_status or "clear",
        risk_score=vessel.risk_score,
        recorded_breaches=[
            {
                "id": b.id,
                "breach_type": b.breach_type,
                "authority": b.sanctioning_authority,
                "sanctioned_entity": b.sanctioned_entity_name,
                "sanctioned_entity_id": b.sanctioned_entity_id,
                "confidence": b.match_confidence,
                "severity": b.severity,
                "status": b.investigation_status,
                "first_detected": b.first_detected_at,
            }
            for b in breaches
        ],
        live_matches=[match_out(m) for m in matches],
        programs_active=programs,
        recommendation=recommendation,
    )


@router.get("/updates", response_model=UpdatesResponse)
def get_updates(
    timeframe: int = Query(7, ge=1, le=365, description="Days"),
    authority: str | None = Query(None, description="Comma-separated: OFAC,EU,UN"),
    type: str | None = Query(None, description="new_designation, delisting, program_change, name_change, relisted, initial_import"),
    entity_type: str | None = None,
    limit: int = Query(200, ge=1, le=2000),
    db: Session = Depends(get_db),
) -> UpdatesResponse:
    end = utcnow()
    start = end - timedelta(days=timeframe)
    stmt = select(SanctionsUpdate).where(SanctionsUpdate.timestamp >= start)
    if authorities := _csv(authority):
        stmt = stmt.where(SanctionsUpdate.authority.in_([a.upper() for a in authorities]))
    if type:
        stmt = stmt.where(SanctionsUpdate.update_type == type)
    if entity_type:
        stmt = stmt.where(SanctionsUpdate.entity_type == entity_type)
    rows = db.execute(stmt.order_by(SanctionsUpdate.timestamp.desc()).limit(limit)).scalars().all()
    summary: dict[str, dict[str, int]] = {}
    for auth, kind, count in db.execute(
        select(SanctionsUpdate.authority, SanctionsUpdate.update_type, func.count()).where(SanctionsUpdate.timestamp >= start).group_by(SanctionsUpdate.authority, SanctionsUpdate.update_type)
    ):
        summary.setdefault(auth, {})[kind] = count
    total = sum(sum(v.values()) for v in summary.values())
    return UpdatesResponse(
        timeframe_days=timeframe,
        period=f"{start.date()} to {end.date()}",
        total_updates=total,
        summary=summary,
        updates=[SanctionsUpdateOut.model_validate(r) for r in rows],
    )


@router.get("/programs", response_model=ProgramsResponse)
def get_programs(authority: str | None = None, db: Session = Depends(get_db)) -> ProgramsResponse:
    stmt = select(SanctionsProgramTracking)
    if authority:
        stmt = stmt.where(SanctionsProgramTracking.authority == authority.upper())
    rows = db.execute(stmt.order_by(SanctionsProgramTracking.authority, SanctionsProgramTracking.entities_in_program.desc())).scalars().all()
    totals = dict(db.execute(select(SanctionsEntity.designating_authority, func.count()).where(SanctionsEntity.is_active.is_(True)).group_by(SanctionsEntity.designating_authority)).all())
    return ProgramsResponse(programs=[ProgramOut.model_validate(r) for r in rows], totals=totals)


@router.get("/report/{timeframe}")
def get_report(timeframe: str, include_programs: str | None = None, authority: str | None = None) -> dict[str, Any]:
    """Recent sanctions-activity report as JSON (``7days``, ``30days``, ``24h``). PDF export arrives in Phase 4."""
    match = re.fullmatch(r"(\d+)\s*(d|days?|h|hours?)", timeframe.strip().lower())
    if not match:
        raise HTTPException(status_code=422, detail="timeframe must look like 7days or 24h")
    amount, unit = int(match.group(1)), match.group(2)
    days = max(1, amount if unit.startswith("d") else (amount + 23) // 24)
    report = sanctions_bot.generate_report(days, _csv(authority) or None)
    if include_programs:
        wanted = [p.upper() for p in _csv(include_programs)]
        report["updates"] = [u for u in report["updates"] if any(w in (p.upper() for p in ((u.get("new") or {}).get("programs") or [])) for w in wanted)]
    return jsonable(report)


@router.get("/status")
def get_status() -> dict[str, Any]:
    return jsonable(sanctions_bot.status())


@router.post("/refresh", status_code=202)
def trigger_refresh(authority: str | None = Query(None, description="Comma-separated subset")) -> dict[str, Any]:
    """Start a list refresh on the bot loop (takes ~15-60 s); poll /status for the result."""
    if sanctions_bot.refreshing:
        return {"status": "already_running"}
    authorities = [a.upper() for a in _csv(authority)] or None
    bot_loop.submit(sanctions_bot.update_all_sanctions(authorities))
    return {"status": "started", "authorities": authorities or ["OFAC", "EU", "UN"]}
