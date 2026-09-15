"""Sanctions-evasion indicators derived from AIS behaviour and identity changes.

All functions are pure: they take the stored vessel state plus the incoming
report and return ``EvasionIndicator`` records for the bot to persist.
"""

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime

from app.analysis.geospatial import describe_location, haversine_m, zones_containing

HIGH_RISK_KINDS = {"sanctions_zone", "war_zone"}

# Plausible top speeds (knots) by declared type; anything faster is a spoofed/garbled report
MAX_SPEED_BY_TYPE = {"high-speed craft": 70.0, "passenger": 45.0, "military": 45.0, "pleasure craft": 60.0, "search and rescue": 50.0, "law enforcement": 50.0}
DEFAULT_MAX_SPEED = 30.0
MAX_IMPLIED_SPEED = 60.0  # between consecutive fixes, any type


@dataclass
class EvasionIndicator:
    event_type: str  # ais_gap, name_change, flag_change, identity_conflict, dark_in_zone
    severity: str
    confidence: float
    timestamp: datetime
    summary: str
    lat: float | None = None
    lon: float | None = None
    details: dict = field(default_factory=dict)


def _risk_context(lat: float | None, lon: float | None) -> list[str]:
    if lat is None or lon is None:
        return []
    return [z.name for z in zones_containing(lat, lon) if z.kind in HIGH_RISK_KINDS]


def detect_ais_gap(
    previous_time: datetime | None,
    previous_speed: float | None,
    previous_lat: float | None,
    previous_lon: float | None,
    position,
    threshold_hours: float = 6.0,
) -> EvasionIndicator | None:
    """A gap longer than ``threshold_hours`` while the vessel was last seen underway.

    Severity rises when either end of the gap lies in a sanctions/war zone -
    'going dark' near restricted waters is the classic evasion signature.
    """
    if previous_time is None:
        return None
    gap_hours = (position.timestamp - previous_time).total_seconds() / 3600
    if gap_hours < threshold_hours:
        return None
    was_underway = (previous_speed or 0) >= 1.0
    zones_before = _risk_context(previous_lat, previous_lon)
    zones_after = _risk_context(position.lat, position.lon)
    in_zone = bool(zones_before or zones_after)
    if in_zone and gap_hours >= threshold_hours * 4:
        severity, confidence = "critical", 0.85
    elif in_zone:
        severity, confidence = "high", 0.7
    elif was_underway and gap_hours >= threshold_hours * 4:
        severity, confidence = "high", 0.6
    elif was_underway:
        severity, confidence = "medium", 0.45
    else:
        severity, confidence = "low", 0.25  # moored/anchored vessels legitimately stop transmitting
    where = describe_location(position.lat, position.lon)
    return EvasionIndicator(
        event_type="ais_gap",
        severity=severity,
        confidence=confidence,
        timestamp=position.timestamp,
        lat=position.lat,
        lon=position.lon,
        summary=f"AIS silent for {gap_hours:.1f} h; reappeared {where}" + (f" - zones: {', '.join(zones_before + zones_after)}" if in_zone else ""),
        details={
            "gap_hours": round(gap_hours, 2),
            "last_seen": previous_time.isoformat(),
            "last_speed": previous_speed,
            "was_underway": was_underway,
            "start": {"lat": previous_lat, "lon": previous_lon},
            "end": {"lat": position.lat, "lon": position.lon},
            "zones_before": zones_before,
            "zones_after": zones_after,
        },
    )


def plausible_max_speed(ship_type: str | None) -> float:
    lowered = (ship_type or "").lower()
    for key, value in MAX_SPEED_BY_TYPE.items():
        if key in lowered:
            return value
    return DEFAULT_MAX_SPEED


def detect_position_anomaly(previous_time: datetime | None, previous_lat: float | None, previous_lon: float | None, position, ship_type: str | None) -> EvasionIndicator | None:
    """Physically impossible reports: absurd speed over ground, or a jump no ship could make.

    Ships 'teleporting' inland or reporting 40+ knots are the fingerprint of
    GNSS spoofing / jamming (endemic in the eastern Baltic and Black Sea) or
    of deliberate AIS manipulation - either way an intelligence indicator.
    """
    reasons: list[str] = []
    details: dict = {"reported_speed": position.speed}
    limit = plausible_max_speed(ship_type)
    if position.speed is not None and position.speed > limit:
        reasons.append(f"reported speed {position.speed:.1f} kn exceeds {limit:.0f} kn for a {ship_type or 'vessel of unknown type'}")
    if previous_time is not None and previous_lat is not None and previous_lon is not None:
        hours = (position.timestamp - previous_time).total_seconds() / 3600
        if hours > 0:
            distance_nm = haversine_m(previous_lat, previous_lon, position.lat, position.lon) / 1852
            implied = distance_nm / hours
            details.update({"distance_nm": round(distance_nm, 1), "minutes": round(hours * 60, 1), "implied_speed_kn": round(implied, 1)})
            if distance_nm > 5 and implied > MAX_IMPLIED_SPEED:
                reasons.append(f"moved {distance_nm:.0f} nm in {hours * 60:.0f} min ({implied:.0f} kn implied)")
    if not reasons:
        return None
    severe = len(reasons) > 1 or details.get("implied_speed_kn", 0) > 200 or (position.speed or 0) > 2 * limit
    return EvasionIndicator(
        event_type="position_anomaly",
        severity="high" if severe else "medium",
        confidence=0.65 if severe else 0.45,
        timestamp=position.timestamp,
        lat=position.lat,
        lon=position.lon,
        summary="Implausible AIS report (possible GNSS spoofing/jamming or manipulated transponder): " + "; ".join(reasons) + f" - reported {describe_location(position.lat, position.lon)}",
        details={**details, "reasons": reasons},
    )


def name_token(value: str | None) -> str:
    """Letters and digits only, upper-case, roman numerals and 'NO.' spellings folded - 'LOCA LOLA 2' == 'LOCA LOLA II'."""
    text = re.sub(r"[^A-Z0-9 ]", " ", (value or "").upper())
    text = re.sub(r"\bNO\.? ?(\d)", r"NO\1", text)
    words = [ROMAN.get(w, w) for w in text.split()]
    return "".join(words)


ROMAN = {"I": "1", "II": "2", "III": "3", "IV": "4", "V": "5", "VI": "6", "VII": "7", "VIII": "8", "IX": "9", "X": "10", "XI": "11", "XII": "12"}


def is_name_variant(old: str | None, new: str | None) -> bool:
    return name_token(old) == name_token(new)


def detect_identity_changes(vessel, position) -> list[EvasionIndicator]:
    """Name / flag changes on the same MMSI, and IMO reported under a new name.

    Cosmetic variants (padding, punctuation, 'NO.2' vs 'NO2', roman numerals) and a flip back to a name the hull carried
    within its recent history (two sources spelling it differently) are not renames.
    """
    indicators = []
    recent = {name_token(n) for n in (getattr(vessel, "historical_names", None) or [])[-3:]}
    if (position.name and vessel.name and position.name.upper() != vessel.name.upper() and not vessel.name.startswith("MMSI ")
            and not is_name_variant(vessel.name, position.name) and name_token(position.name) not in recent):
        indicators.append(
            EvasionIndicator(
                event_type="name_change",
                severity="medium",
                confidence=0.5,
                timestamp=position.timestamp,
                lat=position.lat,
                lon=position.lon,
                summary=f"Vessel renamed from '{vessel.name}' to '{position.name}'",
                details={"old_name": vessel.name, "new_name": position.name},
            )
        )
    if position.flag and vessel.flag_state and position.flag != vessel.flag_state and position.flag != "XX":
        indicators.append(
            EvasionIndicator(
                event_type="flag_change",
                severity="high",
                confidence=0.6,
                timestamp=position.timestamp,
                lat=position.lat,
                lon=position.lon,
                summary=f"Flag changed from {vessel.flag_state} to {position.flag}",
                details={"old_flag": vessel.flag_state, "new_flag": position.flag},
            )
        )
    return indicators


def identity_conflict(existing_vessel, position) -> EvasionIndicator:
    """The reported IMO already belongs to a vessel with a different MMSI (re-registration or spoofing)."""
    flag_changed = existing_vessel.flag_state != position.flag
    return EvasionIndicator(
        event_type="identity_conflict",
        severity="high" if flag_changed else "medium",
        confidence=0.65 if flag_changed else 0.5,
        timestamp=position.timestamp,
        lat=position.lat,
        lon=position.lon,
        summary=(
            f"IMO {position.imo} now transmitting as MMSI {position.mmsi} ({position.name or 'unnamed'}, {position.flag}); "
            f"previously MMSI {existing_vessel.mmsi} ({existing_vessel.name}, {existing_vessel.flag_state})"
        ),
        details={
            "imo": position.imo,
            "previous_mmsi": existing_vessel.mmsi,
            "previous_name": existing_vessel.name,
            "previous_flag": existing_vessel.flag_state,
            "new_mmsi": position.mmsi,
            "new_name": position.name,
            "new_flag": position.flag,
        },
    )


def dark_vessel_indicator(vessel, now: datetime, threshold_hours: float) -> EvasionIndicator | None:
    """A flagged/breach vessel that stopped transmitting inside or near a monitored zone."""
    if not vessel.last_ais_update or vessel.current_position_lat is None:
        return None
    hours = (now - vessel.last_ais_update).total_seconds() / 3600
    if hours < threshold_hours:
        return None
    zones = _risk_context(vessel.current_position_lat, vessel.current_position_lon)
    if not zones and not (vessel.sanctioned_status or "clear").startswith("breach"):
        return None
    return EvasionIndicator(
        event_type="dark_in_zone" if zones else "dark_vessel",
        severity="high" if zones else "medium",
        confidence=0.6 if zones else 0.4,
        timestamp=vessel.last_ais_update,
        lat=vessel.current_position_lat,
        lon=vessel.current_position_lon,
        summary=f"{vessel.name} ({vessel.sanctioned_status}) silent for {hours:.1f} h, last seen {describe_location(vessel.current_position_lat, vessel.current_position_lon)}",
        details={"hours_silent": round(hours, 1), "zones": zones, "sanctioned_status": vessel.sanctioned_status},
    )


# ------------------------------------------------------------- GNSS spoofing
@dataclass
class SpoofingCluster:
    lat: float
    lon: float
    vessels: list[dict]  # {mmsi, name, flag, ship_type, reason}
    inland: bool
    zones: list[str]
    first_seen: datetime
    last_seen: datetime
    anomaly_ids: list[int]

    @property
    def severity(self) -> str:
        n = len(self.vessels)
        if n >= 10 or (self.inland and n >= 5):
            return "critical"
        if n >= 5 or self.inland:
            return "high"
        return "medium"


def spoofing_clusters(anomalies: list, min_vessels: int = 3, cell_deg: float = 0.1) -> list[SpoofingCluster]:
    """Group recent position anomalies into spatial clusters - several hulls jumping to the same spot is the signature
    of GNSS spoofing or jamming (ships "parked" on an airport inland, or stacked on one coordinate off a naval base),
    not of one ship's faulty transponder.

    ``anomalies`` are evasion events of type ``position_anomaly`` with a location.  Cells are ~11 km; a cluster is the
    3x3 neighbourhood around the densest cell, taken greedily until no neighbourhood holds ``min_vessels`` distinct hulls.
    """
    from app.analysis import landmask

    cells: dict[tuple[int, int], list] = defaultdict(list)
    for a in anomalies:
        if a.location_lat is None or a.location_lon is None:
            continue
        cells[(int(a.location_lat // cell_deg), int(a.location_lon // cell_deg))].append(a)

    def neighbourhood(key):
        r, c = key
        return [(r + dr, c + dc) for dr in (-1, 0, 1) for dc in (-1, 0, 1)]

    clusters: list[SpoofingCluster] = []
    while cells:
        best_key, best_vessels = None, 0
        for key in cells:
            hulls = {a.vessel_id for k in neighbourhood(key) for a in cells.get(k, [])}
            if len(hulls) > best_vessels:
                best_key, best_vessels = key, len(hulls)
        if best_vessels < min_vessels:
            break
        members = [a for k in neighbourhood(best_key) for a in cells.pop(k, [])]
        by_vessel: dict[int, object] = {}
        for a in sorted(members, key=lambda a: a.timestamp):
            by_vessel[a.vessel_id] = a  # latest anomaly per hull
        lat = sum(a.location_lat for a in members) / len(members)
        lon = sum(a.location_lon for a in members) / len(members)
        vessels = []
        for a in by_vessel.values():
            vessel = getattr(a, "vessel", None)
            reasons = (a.details or {}).get("reasons") or []
            vessels.append({"mmsi": a.mmsi, "name": getattr(vessel, "name", None), "flag": getattr(vessel, "flag_state", None), "ship_type": getattr(vessel, "ship_type", None),
                            "reason": reasons[0] if reasons else (a.summary or "")[:120]})
        clusters.append(SpoofingCluster(lat=round(lat, 4), lon=round(lon, 4), vessels=vessels, inland=landmask.is_inland(lat, lon, margin_km=5.0),
                                        zones=[z.name for z in zones_containing(lat, lon)], first_seen=min(a.timestamp for a in members), last_seen=max(a.timestamp for a in members),
                                        anomaly_ids=sorted(a.id for a in members if a.id is not None)))
    return clusters


def spoofing_indicator(cluster: SpoofingCluster) -> EvasionIndicator:
    n = len(cluster.vessels)
    where = describe_location(cluster.lat, cluster.lon)
    context = " on land" if cluster.inland else ""
    zone = f" inside {', '.join(cluster.zones)}" if cluster.zones else ""
    types = Counter((v.get("ship_type") or "unknown").split(" ")[0].lower() for v in cluster.vessels)
    return EvasionIndicator(
        event_type="spoofing_cluster",
        severity=cluster.severity,
        confidence=round(min(0.95, 0.5 + 0.05 * n + (0.15 if cluster.inland else 0.0)), 2),
        timestamp=cluster.last_seen,
        lat=cluster.lat,
        lon=cluster.lon,
        summary=f"GNSS spoofing/jamming signature: {n} vessels report implausible positions{context} {where}{zone} between {cluster.first_seen:%H:%M} and {cluster.last_seen:%H:%M} UTC",
        details={"vessel_count": n, "vessels": cluster.vessels[:40], "inland": cluster.inland, "zones": cluster.zones, "types": dict(types), "anomaly_ids": cluster.anomaly_ids[:200],
                 "first_seen": cluster.first_seen.isoformat(), "last_seen": cluster.last_seen.isoformat()},
    )
