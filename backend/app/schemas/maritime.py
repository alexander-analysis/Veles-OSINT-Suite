"""Maritime API schemas (GeoJSON for the map)."""

from datetime import datetime
from typing import Literal

from pydantic import Field

from app.schemas.common import APIModel


class PointGeometry(APIModel):
    type: Literal["Point"] = "Point"
    coordinates: tuple[float, float] = Field(description="[longitude, latitude]")


class VesselProperties(APIModel):
    mmsi: str
    imo: str | None = None
    name: str
    flag: str
    owner: str | None = None
    ship_type: str | None = None
    speed: float | None = None
    heading: float | None = None
    sanctioned_status: str
    risk_score: float | None = None
    last_update: datetime | None = None
    ais_source: str | None = None
    marker_color: str


class VesselFeature(APIModel):
    type: Literal["Feature"] = "Feature"
    geometry: PointGeometry
    properties: VesselProperties


class VesselFeatureCollection(APIModel):
    type: Literal["FeatureCollection"] = "FeatureCollection"
    timestamp: datetime
    vessel_count: int
    breach_count: int
    features: list[VesselFeature]
