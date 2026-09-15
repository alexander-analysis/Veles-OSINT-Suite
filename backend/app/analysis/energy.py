"""Energy flow rules: tanker size classes, cargo estimates, facility geofencing, dark-oil pattern scoring."""

from dataclasses import dataclass
from datetime import datetime

from app.analysis.geospatial import haversine_m
from app.data.energy_facilities import FACILITIES

TANKER_TYPES = ("tanker", "crude", "oil", "chemical", "lng", "lpg", "gas carrier", "product")
SANCTIONED_ORIGINS = {"RU", "IR", "VE", "SY", "KP", "CU"}

# (max length m, class, typical DWT, typical max draught m)
SIZE_CLASSES = [
    (120, "small_tanker", 8_000, 7.0),
    (160, "handysize", 30_000, 9.5),
    (190, "medium_range", 50_000, 12.5),
    (230, "panamax_lr1", 75_000, 14.0),
    (260, "aframax_lr2", 110_000, 15.0),
    (290, "suezmax", 160_000, 17.0),
    (400, "vlcc", 300_000, 21.0),
]
BARRELS_PER_TONNE = {"crude": 7.3, "products": 8.0, "mixed": 7.5, "lpg": 11.0, "lng": 0.0}


def is_tanker(ship_type: str | None) -> bool:
    lowered = (ship_type or "").lower()
    return any(t in lowered for t in TANKER_TYPES)


def matches_commodity(ship_type: str | None, commodity: str | None) -> bool:
    """LNG plants only see gas carriers; oil facilities only tankers (an LNG carrier at a crude terminal is noise)."""
    lowered = (ship_type or "").lower()
    if commodity == "lng":
        return "lng" in lowered or "gas" in lowered
    return is_tanker(ship_type)


def size_class(length_m: float | None) -> tuple[str, float, float] | None:
    if not length_m:
        return None
    for max_len, name, dwt, draught in SIZE_CLASSES:
        if length_m <= max_len:
            return name, dwt, draught
    return "ulcc", 400_000, 23.0


@dataclass
class CargoEstimate:
    laden: bool | None
    barrels: float | None
    size_class: str | None
    basis: str


def estimate_cargo(length_m: float | None, draught_arrival: float | None, draught_departure: float | None, commodity: str | None, loading: bool = True) -> CargoEstimate:
    """Laden / ballast call from draught change and a coarse volume from the size class.

    ``loading=True``: the vessel is leaving an export facility (deeper = loaded).
    ``loading=False``: arriving at a discharge facility (deep on arrival = delivering).
    """
    cls = size_class(length_m)
    if commodity == "lng":
        cls_name = cls[0] if cls else None
        return CargoEstimate(None, None, cls_name, "lng_no_barrel_estimate")
    laden: bool | None = None
    basis = "unknown"
    reference = draught_departure if loading else draught_arrival
    other = draught_arrival if loading else draught_departure
    if reference and other and abs(reference - other) >= 1.0:
        laden = reference > other
        basis = "draught_change"
    elif reference and cls:
        laden = reference >= 0.8 * cls[2]
        basis = "draught_vs_class_max"
    elif reference and reference >= 12.0:
        laden = True
        basis = "deep_draught"
    barrels = None
    if laden and cls:
        factor = BARRELS_PER_TONNE.get(commodity or "crude", 7.3)
        barrels = round(cls[1] * 0.95 * factor)
        if reference and cls[2]:
            barrels = round(barrels * min(1.0, max(0.5, reference / cls[2])))
    return CargoEstimate(laden, barrels, cls[0] if cls else None, basis)


def facility_containing(lat: float | None, lon: float | None) -> tuple[dict, float] | None:
    if lat is None or lon is None:
        return None
    best: tuple[dict, float] | None = None
    for facility in FACILITIES:
        distance_km = haversine_m(lat, lon, facility["lat"], facility["lon"]) / 1000
        if distance_km <= facility["radius_km"] and (best is None or distance_km < best[1]):
            best = (facility, distance_km)
    return best


def facility_by_port(port_name: str | None) -> dict | None:
    if not port_name:
        return None
    return next((f for f in FACILITIES if f.get("port_name") == port_name), None)


# ------------------------------------------------------------- dark oil
PATTERN_SCORES = {
    "sanctioned_loading": (0.55, "medium"),
    "ais_gap_after_loading": (0.75, "high"),
    "sts_transfer": (0.7, "high"),
    "sts_hub_loitering": (0.6, "medium"),
    "spoofed_position": (0.8, "high"),
    "identity_change": (0.65, "high"),
    "sanctioned_vessel_loading": (0.9, "critical"),
    "discharge_to_sanctioned_destination": (0.7, "high"),
}


def score_pattern(pattern: str, vessel_sanctioned: bool, vessel_risk: float | None, extra: float = 0.0) -> tuple[float, str]:
    base, severity = PATTERN_SCORES.get(pattern, (0.5, "medium"))
    score = base + extra
    if vessel_sanctioned:
        score += 0.15
    elif (vessel_risk or 0) >= 0.5:
        score += 0.05
    score = round(min(score, 1.0), 2)
    if score >= 0.85:
        severity = "critical"
    elif score >= 0.7 and severity == "medium":
        severity = "high"
    return score, severity


def days_between(a: datetime | None, b: datetime | None) -> float | None:
    if not a or not b:
        return None
    return abs((b - a).total_seconds()) / 86400


def pearson(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    if n < 5 or n != len(ys):
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx == 0 or syy == 0:
        return None
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    return round(sxy / (sxx * syy) ** 0.5, 3)
