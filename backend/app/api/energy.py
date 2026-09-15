"""/api/energy/* - facilities, tanker shipments, dark-oil indicators, flow series and price context."""

from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.bots.energy import energy_bot
from app.bots.runtime import bot_loop
from app.database import get_db
from app.models.audit import AuditLog
from app.models.energy import DarkOilIndicator, EnergyFacility, EnergyFlowSnapshot, OilTankerShipment
from app.models.maritime import PortCallEvent, Vessel
from app.schemas.energy import DarkOilOut, DarkOilResponse, FacilityDetail, FacilityOut, FlowPoint, FlowsResponse, ShipmentOut, ShipmentsResponse
from app.utils.serialization import jsonable
from app.utils.time import utcnow

router = APIRouter(tags=["energy"])


@router.get("/facilities", response_model=list[FacilityOut])
def list_facilities(country: str | None = None, facility_type: str | None = None, sanctioned: bool | None = None, db: Session = Depends(get_db)) -> list[FacilityOut]:
    query = select(EnergyFacility)
    if country:
        query = query.where(EnergyFacility.country == country.upper())
    if facility_type:
        query = query.where(EnergyFacility.facility_type == facility_type)
    if sanctioned is not None:
        query = query.where(EnergyFacility.is_sanctioned_facility.is_(sanctioned))
    rows = db.execute(query.order_by(EnergyFacility.tanker_calls_30d.desc().nulls_last(), EnergyFacility.facility_name)).scalars().all()
    return [FacilityOut.model_validate(r) for r in rows]


@router.get("/facilities/geojson")
def facilities_geojson(db: Session = Depends(get_db)) -> dict[str, Any]:
    rows = db.execute(select(EnergyFacility)).scalars().all()
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [r.longitude, r.latitude]},
                "properties": jsonable({"id": r.id, "name": r.facility_name, "type": r.facility_type, "country": r.country, "commodity": r.commodity, "sanctioned": r.is_sanctioned_facility,
                                        "owner_sanctioned": r.owner_sanctioned, "calls_7d": r.tanker_calls_7d, "calls_30d": r.tanker_calls_30d, "radius_km": r.radius_km, "last_activity_at": r.last_activity_at,
                                        "capacity_bpd": r.production_capacity_bpd, "capacity_mtpa": r.production_capacity_mtpa, "note": r.notes}),
            }
            for r in rows
            if r.latitude is not None
        ],
    }


@router.get("/facilities/{facility_id}", response_model=FacilityDetail)
def facility_detail(facility_id: int, days: int = Query(30, ge=1, le=180), db: Session = Depends(get_db)) -> FacilityDetail:
    facility = db.get(EnergyFacility, facility_id)
    if facility is None:
        raise HTTPException(status_code=404, detail="Facility not found")
    since = utcnow() - timedelta(days=days)
    calls = db.execute(select(PortCallEvent, Vessel).join(Vessel, Vessel.id == PortCallEvent.vessel_id).where(PortCallEvent.energy_facility_id == facility_id, PortCallEvent.arrival_time >= since)
                       .order_by(PortCallEvent.arrival_time.desc()).limit(100)).all()
    shipments = db.execute(select(OilTankerShipment).where(or_(OilTankerShipment.loading_facility_id == facility_id, OilTankerShipment.discharge_facility_id == facility_id), OilTankerShipment.loading_date >= since)
                           .order_by(OilTankerShipment.loading_date.desc()).limit(100)).scalars().all()
    flows = db.execute(select(EnergyFlowSnapshot).where(EnergyFlowSnapshot.facility_id == facility_id, EnergyFlowSnapshot.day >= since).order_by(EnergyFlowSnapshot.day)).scalars().all()
    return FacilityDetail(
        facility=FacilityOut.model_validate(facility),
        recent_calls=[jsonable({"id": c.id, "vessel_id": v.id, "mmsi": v.mmsi, "vessel_name": v.name, "flag": v.flag_state, "ship_type": v.ship_type, "arrival_time": c.arrival_time, "departure_time": c.departure_time,
                                "dwell_time_hours": c.dwell_time_hours, "draught_arrival": c.draught_arrival, "draught_departure": c.draught_departure, "sanctioned_status": v.sanctioned_status, "risk_score": v.risk_score, "flags": c.flags_raised}) for c, v in calls],
        shipments=[ShipmentOut.model_validate(s) for s in shipments],
        flows=[FlowPoint.model_validate(f) for f in flows],
    )


@router.get("/shipments", response_model=ShipmentsResponse)
def list_shipments(
    days: int = Query(30, ge=1, le=365),
    sanctioned_only: bool = False,
    dark_oil_only: bool = False,
    origin: str | None = None,
    destination: str | None = None,
    status: str | None = None,
    mmsi: str | None = None,
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
) -> ShipmentsResponse:
    since = utcnow() - timedelta(days=days)
    query = select(OilTankerShipment).where(OilTankerShipment.loading_date >= since)
    if sanctioned_only:
        query = query.where(OilTankerShipment.sanctioned_route.is_(True))
    if dark_oil_only:
        query = query.where(OilTankerShipment.dark_oil_suspect.is_(True))
    if origin:
        query = query.where(OilTankerShipment.origin_country == origin.upper())
    if destination:
        query = query.where(OilTankerShipment.destination_country == destination.upper())
    if status:
        query = query.where(OilTankerShipment.status == status)
    if mmsi:
        query = query.where(OilTankerShipment.mmsi == mmsi)
    total = db.execute(select(func.count()).select_from(query.subquery())).scalar() or 0
    rows = db.execute(query.order_by(OilTankerShipment.loading_date.desc()).limit(limit)).scalars().all()
    return ShipmentsResponse(total=total, limit=limit, filters={"days": days, "sanctioned_only": sanctioned_only, "dark_oil_only": dark_oil_only, "origin": origin, "destination": destination, "status": status}, shipments=[ShipmentOut.model_validate(r) for r in rows])


@router.get("/dark-oil", response_model=DarkOilResponse)
def list_dark_oil(days: int = Query(30, ge=1, le=365), pattern: str | None = None, min_confidence: float = Query(0.0, ge=0, le=1), status: str | None = None, limit: int = Query(100, ge=1, le=1000), db: Session = Depends(get_db)) -> DarkOilResponse:
    since = utcnow() - timedelta(days=days)
    query = select(DarkOilIndicator).where(DarkOilIndicator.detected_at >= since, DarkOilIndicator.confidence_score >= min_confidence)
    if pattern:
        query = query.where(DarkOilIndicator.detected_pattern == pattern)
    if status:
        query = query.where(DarkOilIndicator.investigation_status == status)
    total = db.execute(select(func.count()).select_from(query.subquery())).scalar() or 0
    rows = db.execute(query.order_by(DarkOilIndicator.confidence_score.desc(), DarkOilIndicator.detected_at.desc()).limit(limit)).scalars().all()
    return DarkOilResponse(total=total, limit=limit, filters={"days": days, "pattern": pattern, "min_confidence": min_confidence, "status": status}, indicators=[DarkOilOut.model_validate(r) for r in rows])


@router.post("/dark-oil/{indicator_id}/status", response_model=DarkOilOut)
def set_dark_oil_status(indicator_id: int, status: str = Query(pattern="^(flagged|investigating|confirmed|cleared)$"), analyst: str | None = Query(None, max_length=100), notes: str | None = Query(None, max_length=500), db: Session = Depends(get_db)) -> DarkOilOut:
    row = db.get(DarkOilIndicator, indicator_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Indicator not found")
    previous = row.investigation_status
    row.investigation_status = status
    db.add(AuditLog(action_type="investigation_updated" if status != "cleared" else "cleared", user_id=analyst or "analyst", vessel_id=row.tanker_id, rationale=notes or f"Dark-oil indicator {row.detected_pattern}: {previous} -> {status}",
                    supporting_data={"indicator_id": indicator_id, "pattern": row.detected_pattern, "previous": previous, "new": status}, source_systems=["api.energy"], created_by=analyst or "analyst"))
    db.commit()
    db.refresh(row)
    return DarkOilOut.model_validate(row)


@router.get("/flows", response_model=FlowsResponse)
def flows(days: int = Query(30, ge=1, le=365), facility_id: int | None = None, country: str | None = None, sanctioned_only: bool = False, db: Session = Depends(get_db)) -> FlowsResponse:
    since = utcnow() - timedelta(days=days)
    query = select(EnergyFlowSnapshot).where(EnergyFlowSnapshot.day >= since)
    if facility_id:
        query = query.where(EnergyFlowSnapshot.facility_id == facility_id)
    if country or sanctioned_only:
        fq = select(EnergyFacility.id)
        if country:
            fq = fq.where(EnergyFacility.country == country.upper())
        if sanctioned_only:
            fq = fq.where(EnergyFacility.is_sanctioned_facility.is_(True))
        query = query.where(EnergyFlowSnapshot.facility_id.in_(fq))
    rows = db.execute(query.order_by(EnergyFlowSnapshot.day, EnergyFlowSnapshot.facility_id)).scalars().all()
    return FlowsResponse(days=days, facility_id=facility_id, country=country, points=[FlowPoint.model_validate(r) for r in rows])


@router.get("/price-context")
def price_context(days: int = Query(30, ge=7, le=180), db: Session = Depends(get_db)) -> dict[str, Any]:
    return jsonable(energy_bot.price_context(db, days))


@router.get("/summary")
def summary(days: int = Query(7, ge=1, le=90), db: Session = Depends(get_db)) -> dict[str, Any]:
    return jsonable(energy_bot.summary(db, days))


@router.get("/status")
def get_status() -> dict[str, Any]:
    return jsonable(energy_bot.status())


@router.post("/refresh", status_code=202)
def trigger_refresh(job: str = Query("all", pattern="^(all|facilities|visits|shipments|dark_oil|snapshots)$")) -> dict[str, Any]:
    jobs = {"facilities": energy_bot.sync_facilities, "visits": energy_bot.track_facility_visits, "shipments": energy_bot.build_shipments, "dark_oil": energy_bot.detect_dark_oil, "snapshots": energy_bot.snapshot_flows}
    selected = list(jobs) if job == "all" else [job]
    for name in selected:
        bot_loop.submit(jobs[name]())
    return {"status": "started", "jobs": selected}
