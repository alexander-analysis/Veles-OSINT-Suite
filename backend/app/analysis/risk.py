"""Composite vessel risk score (0-1).

Independent signals are combined as ``1 - prod(1 - w_i)`` so several weak
indicators add up without any single one saturating the score:

* strongest sanctions match confidence (direct/owner/flag)
* evasion indicators in the last 30 days (weighted by severity)
* calls at sanctioned / high-risk facilities in the last 30 days
* ship-to-ship rendezvous in the last 30 days
* flag of convenience typical of the shadow fleet (small bump)
"""

from datetime import timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models.maritime import EvasionEvent, PortCallEvent, SanctionsBreach, TransshipmentEvent, Vessel
from app.utils.time import utcnow

SEVERITY_WEIGHT = {"low": 0.05, "medium": 0.12, "high": 0.25, "critical": 0.4}
SHADOW_FLEET_FLAGS = {"GA", "CM", "SL", "KM", "PW", "CK", "SM", "GM", "TZ", "MN", "XX"}


def combine(weights: list[float]) -> float:
    score = 1.0
    for weight in weights:
        score *= 1 - max(0.0, min(0.99, weight))
    return round(1 - score, 3)


def compute_risk_score(db: Session, vessel: Vessel, days: int = 30) -> tuple[float, dict]:
    since = utcnow() - timedelta(days=days)
    weights: list[float] = []
    factors: dict = {}

    top_breach = db.execute(
        select(func.max(SanctionsBreach.match_confidence)).where(SanctionsBreach.vessel_id == vessel.id, SanctionsBreach.investigation_status != "cleared")
    ).scalar()
    if top_breach:
        weights.append(float(top_breach))
        factors["sanctions_match"] = float(top_breach)

    evasion = db.execute(select(EvasionEvent.severity, func.count()).where(EvasionEvent.vessel_id == vessel.id, EvasionEvent.timestamp >= since).group_by(EvasionEvent.severity)).all()
    if evasion:
        weight = min(0.7, sum(SEVERITY_WEIGHT.get(sev, 0.1) * count for sev, count in evasion))
        weights.append(weight)
        factors["evasion_indicators"] = {sev: count for sev, count in evasion}

    risky_calls = db.execute(
        select(func.count()).where(PortCallEvent.vessel_id == vessel.id, PortCallEvent.arrival_time >= since, or_(PortCallEvent.is_sanctioned_facility.is_(True), PortCallEvent.facility_risk_level == "high"))
    ).scalar() or 0
    if risky_calls:
        weights.append(min(0.45, 0.15 * risky_calls))
        factors["high_risk_port_calls"] = risky_calls

    sts = db.execute(
        select(func.count()).where(or_(TransshipmentEvent.vessel_a_id == vessel.id, TransshipmentEvent.vessel_b_id == vessel.id), TransshipmentEvent.timestamp >= since, TransshipmentEvent.investigation_status != "cleared")
    ).scalar() or 0
    if sts:
        weights.append(min(0.5, 0.2 * sts))
        factors["transshipments"] = sts

    if vessel.flag_state in SHADOW_FLEET_FLAGS and "tanker" in (vessel.ship_type or "").lower():
        weights.append(0.1)
        factors["flag_of_convenience_tanker"] = vessel.flag_state

    return combine(weights), factors
