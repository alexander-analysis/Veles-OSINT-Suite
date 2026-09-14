"""Geospatial primitives: distances, zone / lane containment, nearest port."""

import math
from dataclasses import dataclass
from functools import lru_cache

from shapely.geometry import Point, Polygon
from shapely.prepared import prep

from app.data.ports import PORTS
from app.data.zones import LANES, ZONES

EARTH_RADIUS_M = 6_371_000.0
NM_PER_M = 1 / 1852.0


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in metres."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


@dataclass(frozen=True)
class Area:
    name: str
    kind: str  # sanctions_zone | war_zone | piracy_zone | lane
    authorities: tuple[str, ...]
    context: str
    choke_point: bool
    polygon: Polygon
    prepared: object  # prepared geometry for fast containment


@lru_cache(maxsize=1)
def zone_areas() -> list[Area]:
    areas = []
    for zone in ZONES:
        polygon = Polygon(zone["ring"])
        areas.append(Area(zone["name"], zone["kind"], tuple(zone["authorities"]), zone["context"], False, polygon, prep(polygon)))
    return areas


@lru_cache(maxsize=1)
def lane_areas() -> list[Area]:
    areas = []
    for lane in LANES:
        polygon = Polygon(lane["ring"])
        areas.append(Area(lane["name"], "lane", (), "", lane["choke_point"], polygon, prep(polygon)))
    return areas


def zones_containing(lat: float, lon: float) -> list[Area]:
    point = Point(lon, lat)
    return [area for area in zone_areas() if area.prepared.contains(point)]


def lanes_containing(lat: float, lon: float) -> list[Area]:
    point = Point(lon, lat)
    return [area for area in lane_areas() if area.prepared.contains(point)]


def nearest_port(lat: float, lon: float, within_km: float | None = None) -> tuple[dict, float] | None:
    """Closest curated port and its distance in km (optionally only if inside ``within_km``)."""
    best, best_km = None, float("inf")
    for port in PORTS:
        # cheap bounding pre-filter (~2 degrees) before the haversine
        if abs(port["lat"] - lat) > 2 or abs(port["lon"] - lon) > 3:
            continue
        km = haversine_m(lat, lon, port["lat"], port["lon"]) / 1000
        if km < best_km:
            best, best_km = port, km
    if best is None or (within_km is not None and best_km > within_km):
        return None
    return best, best_km


def port_containing(lat: float, lon: float) -> tuple[dict, float] | None:
    """Port whose detection radius contains the point."""
    found = nearest_port(lat, lon)
    if found and found[1] <= found[0]["radius_km"]:
        return found
    return None


def describe_location(lat: float, lon: float) -> str:
    """Human-readable location: nearest port / zone / lane, else coordinates."""
    port = nearest_port(lat, lon, within_km=40)
    if port:
        return f"{port[1]:.0f} km from {port[0]['name']} ({port[0]['country']})"
    zones = zones_containing(lat, lon)
    if zones:
        return zones[0].name
    lanes = lanes_containing(lat, lon)
    if lanes:
        return lanes[0].name
    return f"{lat:.3f}, {lon:.3f}"
