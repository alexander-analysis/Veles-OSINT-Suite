"""Is a coordinate on land, and how far is it from the coast?

Backed by the Natural Earth 1:50m land polygons (public domain, vendored as
``app/data/ne_50m_land.json.gz``: 1,421 polygons, ~60k vertices, coastline
accuracy of roughly a kilometre or two).  Rivers, canals and lakes are land in
this dataset, which is exactly what the maritime bots need: a "rendezvous" on a
Dutch canal or the Elbe is barge traffic, not a ship-to-ship transfer.

Point-in-polygon runs on a per-ring latitude-band edge index so a lookup costs a
few hundred edge tests instead of a walk over a 20k-vertex continent; nearest
coastline distance uses a 1-degree vertex grid.
"""

import gzip
import json
import math
from collections import defaultdict
from functools import lru_cache
from pathlib import Path

from app.analysis.geospatial import haversine_m

DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "ne_50m_land.json.gz"


class _Ring:
    __slots__ = ("xs", "ys", "bbox", "bands")

    def __init__(self, flat: list[float]) -> None:
        self.xs = flat[0::2]
        self.ys = flat[1::2]
        self.bbox = (min(self.xs), min(self.ys), max(self.xs), max(self.ys))
        bands: dict[int, list[int]] = defaultdict(list)
        n = len(self.xs)
        for i in range(n):
            j = (i + 1) % n
            lo, hi = sorted((self.ys[i], self.ys[j]))
            for band in range(math.floor(lo), math.floor(hi) + 1):
                bands[band].append(i)
        self.bands = dict(bands)

    def contains(self, lon: float, lat: float) -> bool:
        x0, y0, x1, y1 = self.bbox
        if not (x0 <= lon <= x1 and y0 <= lat <= y1):
            return False
        inside = False
        xs, ys, n = self.xs, self.ys, len(self.xs)
        for i in self.bands.get(math.floor(lat), ()):
            j = (i + 1) % n
            if (ys[i] > lat) != (ys[j] > lat):
                if lon < (xs[j] - xs[i]) * (lat - ys[i]) / (ys[j] - ys[i]) + xs[i]:
                    inside = not inside
        return inside


class _Polygon:
    __slots__ = ("outer", "holes")

    def __init__(self, rings: list[list[float]]) -> None:
        self.outer = _Ring(rings[0])
        self.holes = [_Ring(r) for r in rings[1:]]

    def contains(self, lon: float, lat: float) -> bool:
        return self.outer.contains(lon, lat) and not any(h.contains(lon, lat) for h in self.holes)


class LandMask:
    def __init__(self, polygons: list[_Polygon]) -> None:
        self.polygons = polygons
        self.vertex_grid: dict[tuple[int, int], list[tuple[float, float]]] = defaultdict(list)
        for poly in polygons:
            for ring in (poly.outer, *poly.holes):
                for x, y in zip(ring.xs, ring.ys):
                    self.vertex_grid[(math.floor(y), math.floor(x))].append((y, x))

    def is_land(self, lat: float, lon: float) -> bool:
        return any(p.contains(lon, lat) for p in self.polygons)

    def coast_distance_km(self, lat: float, lon: float, search_deg: int = 1) -> float | None:
        """Distance to the nearest coastline vertex within ``search_deg`` grid cells; None when no coast is that close (deep inland / open ocean)."""
        best: float | None = None
        row, col = math.floor(lat), math.floor(lon)
        for dr in range(-search_deg, search_deg + 1):
            for dc in range(-search_deg, search_deg + 1):
                for vy, vx in self.vertex_grid.get((row + dr, ((col + dc + 180) % 360) - 180), ()):
                    d = haversine_m(lat, lon, vy, vx) / 1000
                    if best is None or d < best:
                        best = d
        return best


@lru_cache(maxsize=1)
def mask() -> LandMask:
    with gzip.open(DATA_FILE, "rt", encoding="utf-8") as fh:
        raw = json.load(fh)
    return LandMask([_Polygon(rings) for rings in raw])


def is_land(lat: float, lon: float) -> bool:
    return mask().is_land(lat, lon)


def coast_distance_km(lat: float, lon: float) -> float | None:
    return mask().coast_distance_km(lat, lon)


@lru_cache(maxsize=200_000)
def _is_inland(lat: float, lon: float, margin_km: float) -> bool:
    if not is_land(lat, lon):
        return False
    distance = coast_distance_km(lat, lon)
    return distance is None or distance > margin_km


def is_inland(lat: float, lon: float, margin_km: float = 3.0) -> bool:
    """On land *and* more than ``margin_km`` from the nearest coastline vertex - beyond the dataset's own coastal uncertainty.

    Coordinates are rounded to ~1 km so repeated lookups in the same anchorage hit the cache.
    """
    return _is_inland(round(lat, 2), round(lon, 2), margin_km)
