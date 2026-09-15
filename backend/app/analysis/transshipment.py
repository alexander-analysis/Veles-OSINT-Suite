"""Ship-to-ship (STS) transfer detection by proximity clustering.

Two vessels loitering within ``proximity_meters`` of each other, both nearly
stationary, away from any port, for at least ``min_duration_minutes`` is the
STS signature.  Candidate pairs come from a coarse lat/lon grid so the check
stays O(n) for thousands of vessels; duration is measured from the stored
position history of both vessels.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from app.analysis.geospatial import describe_location, haversine_m, nearest_port, zones_containing

CARGO_TYPES = ("tanker", "cargo")  # typed hulls that plausibly transfer cargo
EXCLUDED_TYPES = ("tug", "pilot", "passenger", "fishing", "search and rescue", "port tender", "sailing", "pleasure", "law enforcement", "military", "dredging", "hsc", "wing in ground", "diving", "towing")
FISHING_NAME_HINTS = ("F/V", "F\\V", "FV ", "MFV", "FISHING", "TRAWLER")
MOORED_STATUSES = ("moored", "aground")


@dataclass
class TransshipmentCandidate:
    vessel_a: object
    vessel_b: object
    lat: float
    lon: float
    distance_m: float
    duration_minutes: int
    started_at: datetime
    confidence: float
    summary: str
    evidence: dict = field(default_factory=dict)


def _plausible(vessel) -> bool:
    ship_type = (vessel.ship_type or "").lower()
    if any(excluded in ship_type for excluded in EXCLUDED_TYPES):
        return False
    name = (getattr(vessel, "name", None) or "").upper()
    if any(name.startswith(hint) or (hint in name and len(hint) > 3) for hint in FISHING_NAME_HINTS):
        return False
    return (getattr(vessel, "ais_status", None) or "") not in MOORED_STATUSES  # alongside a berth is not a rendezvous


def _typed(vessel) -> bool:
    ship_type = (vessel.ship_type or "").lower()
    return any(kind in ship_type for kind in CARGO_TYPES)


def _tanker(vessel) -> bool:
    return "tanker" in (vessel.ship_type or "").lower()


def _stationary(vessel, max_speed: float) -> bool:
    return vessel.current_speed is not None and vessel.current_speed <= max_speed


def find_proximity_pairs(vessels: list, proximity_meters: float, max_speed_knots: float = 1.5, min_port_distance_km: float = 3.0, cluster_limit: int = 8) -> list[tuple]:
    """Pairs of slow, plausible cargo vessels within ``proximity_meters`` of each other and away from ports.

    Returns ``(a, b, distance_m, neighbours)`` tuples; ``neighbours`` is the number of slow vessels in the
    surrounding ~6 km, the anchorage / marina density cue.  Untyped class-B craft rafted together in a
    marina and barges moored along inland waterways produced tens of thousands of false rendezvous, so a
    pair needs at least one typed tanker / cargo hull, and inside a dense cluster it needs a tanker and two
    typed hulls.
    """
    cell = 0.02  # ~2 km grid cells
    grid: dict[tuple[int, int], list] = defaultdict(list)
    for vessel in vessels:
        if vessel.current_position_lat is None or not _plausible(vessel) or not _stationary(vessel, max_speed_knots):
            continue
        grid[(int(vessel.current_position_lat // cell), int(vessel.current_position_lon // cell))].append(vessel)

    pairs = []
    seen: set[tuple[int, int]] = set()
    for (row, col), members in grid.items():
        neighbours = [v for dr in (-1, 0, 1) for dc in (-1, 0, 1) for v in grid.get((row + dr, col + dc), [])]
        dense = len(neighbours) >= cluster_limit
        for a in members:
            for b in neighbours:
                if a.id >= b.id or (a.id, b.id) in seen:
                    continue
                typed_a, typed_b = _typed(a), _typed(b)
                if not (typed_a or typed_b):
                    continue  # two untyped craft: overwhelmingly small boats, not a cargo transfer
                if dense and not (typed_a and typed_b and (_tanker(a) or _tanker(b))):
                    continue  # anchorage / harbour cluster: only a typed tanker pairing is worth a look
                distance = haversine_m(a.current_position_lat, a.current_position_lon, b.current_position_lat, b.current_position_lon)
                if distance > proximity_meters:
                    continue
                port = nearest_port(a.current_position_lat, a.current_position_lon, within_km=min_port_distance_km)
                if port:
                    continue  # berthed side by side in port is not an STS transfer
                seen.add((a.id, b.id))
                pairs.append((a, b, distance, len(neighbours)))
    return pairs


def proximity_duration(history_a: list, history_b: list, proximity_meters: float, window: timedelta) -> tuple[int, datetime | None]:
    """Minutes the two tracks stayed within ``proximity_meters`` (looking back ``window``), and when that started."""
    if not history_a or not history_b:
        return 0, None
    # Walk the more frequent track and pair each fix with the closest-in-time fix of the other vessel
    a = sorted(history_a, key=lambda p: p.timestamp)
    b = sorted(history_b, key=lambda p: p.timestamp)
    start = None
    last_close = None
    j = 0
    for fix in a:
        while j + 1 < len(b) and abs((b[j + 1].timestamp - fix.timestamp).total_seconds()) <= abs((b[j].timestamp - fix.timestamp).total_seconds()):
            j += 1
        partner = b[j]
        if abs((partner.timestamp - fix.timestamp).total_seconds()) > 900:
            continue
        close = haversine_m(fix.latitude, fix.longitude, partner.latitude, partner.longitude) <= proximity_meters * 1.5
        if close:
            if start is None:
                start = fix.timestamp
            last_close = fix.timestamp
        elif start is not None and last_close and (fix.timestamp - last_close) > timedelta(minutes=20):
            start, last_close = None, None  # contact broke - restart the clock
    if start is None or last_close is None:
        return 0, None
    return int((last_close - start).total_seconds() // 60), start


def assess_candidate(a, b, distance_m: float, duration_minutes: int, started_at: datetime | None, min_duration: int, now: datetime, neighbours: int = 0, cluster_limit: int = 8) -> TransshipmentCandidate | None:
    if duration_minutes < min_duration:
        return None
    lat = (a.current_position_lat + b.current_position_lat) / 2
    lon = (a.current_position_lon + b.current_position_lon) / 2
    types = {(a.ship_type or "").lower(), (b.ship_type or "").lower()}
    confidence = 0.4 if _typed(a) and _typed(b) else 0.3
    confidence += min(0.25, duration_minutes / 480 * 0.25)  # up to +0.25 for an 8 h rendezvous
    if any("tanker" in t for t in types):
        confidence += 0.15
    if neighbours >= cluster_limit:
        confidence -= 0.1  # a crowded anchorage is a weaker signal than two ships alone at sea
    zones = [z.name for z in zones_containing(lat, lon)]
    if zones:
        confidence += 0.1
    risky = [v for v in (a, b) if (v.sanctioned_status or "clear") != "clear" or (v.risk_score or 0) >= 0.5]
    if risky:
        confidence += 0.1
    confidence = round(min(0.97, confidence), 2)
    return TransshipmentCandidate(
        vessel_a=a,
        vessel_b=b,
        lat=lat,
        lon=lon,
        distance_m=round(distance_m),
        duration_minutes=duration_minutes,
        started_at=started_at or now,
        confidence=confidence,
        summary=(
            f"{a.name} ({a.flag_state}) and {b.name} ({b.flag_state}) within {distance_m:.0f} m for {duration_minutes} min "
            f"{describe_location(lat, lon)}" + (f" - inside {', '.join(zones)}" if zones else "")
        ),
        evidence={
            "distance_m": round(distance_m),
            "duration_minutes": duration_minutes,
            "speeds": {a.mmsi: a.current_speed, b.mmsi: b.current_speed},
            "types": {a.mmsi: a.ship_type, b.mmsi: b.ship_type},
            "zones": zones,
            "risk_flags": [v.mmsi for v in risky],
            "neighbours": neighbours,
        },
    )
