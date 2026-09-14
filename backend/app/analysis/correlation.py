"""Entity linkage: which vessels are connected to a given vessel, and why.

Links (each with a weight used for the composite risk score):

* ``shared_owner`` / ``shared_operator`` / ``shared_beneficial_owner`` - same
  declared company on the vessel record
* ``shared_sanctions_entity`` - breaches pointing at the same designated entity
* ``transshipment_partner`` - detected STS rendezvous
* ``shared_high_risk_port`` - both called at the same high-risk facility recently
"""

from collections import defaultdict
from datetime import timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.maritime import PortCallEvent, SanctionsBreach, TransshipmentEvent, Vessel
from app.utils.time import utcnow

LINK_WEIGHTS = {
    "shared_owner": 0.6,
    "shared_beneficial_owner": 0.7,
    "shared_operator": 0.5,
    "shared_sanctions_entity": 0.8,
    "transshipment_partner": 0.7,
    "shared_high_risk_port": 0.3,
}


def correlated_vessels(db: Session, vessel: Vessel, days: int = 30, limit: int = 50) -> list[dict]:
    """Return ``[{mmsi, name, flag, risk_score, sanctioned_status, reasons: [...], link_strength}]``."""
    links: dict[int, dict] = defaultdict(lambda: {"reasons": [], "strength": 0.0})

    def add(other: Vessel, reason: str, detail: str) -> None:
        if other.id == vessel.id:
            return
        entry = links[other.id]
        entry["vessel"] = other
        entry["reasons"].append({"type": reason, "detail": detail})
        entry["strength"] = 1 - (1 - entry["strength"]) * (1 - LINK_WEIGHTS.get(reason, 0.3))

    for attribute, reason in (("owner_name", "shared_owner"), ("registered_operator", "shared_operator"), ("beneficial_owner", "shared_beneficial_owner")):
        value = getattr(vessel, attribute)
        if not value:
            continue
        for other in db.execute(select(Vessel).where(getattr(Vessel, attribute) == value, Vessel.id != vessel.id).limit(limit)).scalars():
            add(other, reason, value)

    entity_ids = {b.sanctioned_entity_id for b in vessel.breaches if b.sanctioned_entity_id}
    if entity_ids:
        for breach in db.execute(select(SanctionsBreach).where(SanctionsBreach.sanctioned_entity_id.in_(entity_ids), SanctionsBreach.vessel_id != vessel.id).limit(limit)).scalars():
            if breach.vessel:
                add(breach.vessel, "shared_sanctions_entity", breach.sanctioned_entity_name)

    since = utcnow() - timedelta(days=days)
    for event in db.execute(
        select(TransshipmentEvent).where(or_(TransshipmentEvent.vessel_a_id == vessel.id, TransshipmentEvent.vessel_b_id == vessel.id), TransshipmentEvent.timestamp >= since).limit(limit)
    ).scalars():
        other = event.vessel_b if event.vessel_a_id == vessel.id else event.vessel_a
        if other:
            add(other, "transshipment_partner", f"{event.timestamp:%Y-%m-%d} - {event.duration_minutes or 0} min, {event.proximity_meters or 0:.0f} m")

    risky_ports = {
        call.port_name
        for call in db.execute(select(PortCallEvent).where(PortCallEvent.vessel_id == vessel.id, PortCallEvent.arrival_time >= since)).scalars()
        if call.is_sanctioned_facility or call.facility_risk_level == "high"
    }
    if risky_ports:
        for call in db.execute(
            select(PortCallEvent).where(PortCallEvent.port_name.in_(risky_ports), PortCallEvent.vessel_id != vessel.id, PortCallEvent.arrival_time >= since).limit(limit * 4)
        ).scalars():
            if call.vessel:
                add(call.vessel, "shared_high_risk_port", call.port_name)

    results = []
    for entry in links.values():
        other = entry["vessel"]
        results.append(
            {
                "mmsi": other.mmsi,
                "imo": other.imo,
                "name": other.name,
                "flag": other.flag_state,
                "ship_type": other.ship_type,
                "risk_score": other.risk_score,
                "sanctioned_status": other.sanctioned_status,
                "reasons": entry["reasons"],
                "link_strength": round(entry["strength"], 2),
            }
        )
    results.sort(key=lambda r: (r["link_strength"], r["risk_score"] or 0), reverse=True)
    return results[:limit]


def fleet_groups(db: Session, min_size: int = 2, limit: int = 30) -> list[dict]:
    """Groups of vessels sharing a declared owner/operator/beneficial owner."""
    groups: dict[tuple[str, str], list[Vessel]] = defaultdict(list)
    for vessel in db.execute(select(Vessel).where(or_(Vessel.owner_name.isnot(None), Vessel.registered_operator.isnot(None), Vessel.beneficial_owner.isnot(None)))).scalars():
        for attribute in ("owner_name", "registered_operator", "beneficial_owner"):
            value = getattr(vessel, attribute)
            if value:
                groups[(attribute, value)].append(vessel)
    out = []
    for (attribute, value), members in groups.items():
        if len(members) < min_size:
            continue
        out.append(
            {
                "link": attribute,
                "entity": value,
                "size": len(members),
                "max_risk": max((m.risk_score or 0) for m in members),
                "flagged": sum(1 for m in members if (m.sanctioned_status or "clear") != "clear"),
                "vessels": [{"mmsi": m.mmsi, "name": m.name, "flag": m.flag_state, "risk_score": m.risk_score, "sanctioned_status": m.sanctioned_status} for m in members[:25]],
            }
        )
    out.sort(key=lambda g: (g["flagged"], g["max_risk"], g["size"]), reverse=True)
    return out[:limit]
