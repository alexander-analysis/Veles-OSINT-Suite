"""/api/maritime/* - maritime intelligence endpoints.

Phase 1 ships ``GET /vessels`` as GeoJSON for the map, reading whatever
vessels exist (none until the maritime bot lands in Phase 3).
"""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.maritime import Vessel
from app.schemas.maritime import PointGeometry, VesselFeature, VesselFeatureCollection, VesselProperties
from app.utils.time import utcnow

router = APIRouter(tags=["maritime"])

# Marker colours match the frontend legend: clear / flagged / breach
MARKER_COLORS = {"clear": "#2ecc71", "flagged": "#f39c12", "breach": "#e74c3c"}


def marker_color(sanctioned_status: str | None) -> str:
    if sanctioned_status and sanctioned_status.startswith("breach"):
        return MARKER_COLORS["breach"]
    if sanctioned_status == "flagged":
        return MARKER_COLORS["flagged"]
    return MARKER_COLORS["clear"]


def parse_bbox(value: str) -> tuple[float, float, float, float]:
    """``min_lon,min_lat,max_lon,max_lat`` -> floats, validated."""
    try:
        parts = [float(part) for part in value.split(",")]
    except ValueError:
        parts = []
    if len(parts) != 4:
        raise HTTPException(status_code=422, detail="bbox must be 'min_lon,min_lat,max_lon,max_lat'")
    min_lon, min_lat, max_lon, max_lat = parts
    if not (-180 <= min_lon <= max_lon <= 180 and -90 <= min_lat <= max_lat <= 90):
        raise HTTPException(status_code=422, detail="bbox out of range or min > max")
    return min_lon, min_lat, max_lon, max_lat


@router.get("/vessels", response_model=VesselFeatureCollection)
def get_vessels(
    bbox: str = Query("-180,-90,180,90", description="min_lon,min_lat,max_lon,max_lat"),
    risk_filter: Literal["all", "flagged", "breach"] = Query("all"),
    limit: int = Query(5000, ge=1, le=20000),
    db: Session = Depends(get_db),
) -> VesselFeatureCollection:
    """Current vessel positions as a GeoJSON FeatureCollection."""
    min_lon, min_lat, max_lon, max_lat = parse_bbox(bbox)

    query = select(Vessel).where(
        Vessel.current_position_lat.between(min_lat, max_lat),
        Vessel.current_position_lon.between(min_lon, max_lon),
    )
    if risk_filter == "breach":
        query = query.where(Vessel.sanctioned_status.like("breach%"))
    elif risk_filter == "flagged":
        query = query.where((Vessel.sanctioned_status == "flagged") | Vessel.sanctioned_status.like("breach%"))

    vessels = db.execute(query.order_by(Vessel.last_ais_update.desc()).limit(limit)).scalars().all()

    features = [
        VesselFeature(
            geometry=PointGeometry(coordinates=(vessel.current_position_lon, vessel.current_position_lat)),
            properties=VesselProperties(
                mmsi=vessel.mmsi,
                imo=vessel.imo,
                name=vessel.name,
                flag=vessel.flag_state,
                owner=vessel.owner_name,
                ship_type=vessel.ship_type,
                speed=vessel.current_speed,
                heading=vessel.current_heading,
                sanctioned_status=vessel.sanctioned_status or "clear",
                risk_score=vessel.risk_score,
                last_update=vessel.last_ais_update,
                ais_source=vessel.ais_source,
                marker_color=marker_color(vessel.sanctioned_status),
            ),
        )
        for vessel in vessels
    ]
    breach_count = sum(1 for vessel in vessels if (vessel.sanctioned_status or "").startswith("breach"))
    return VesselFeatureCollection(
        timestamp=utcnow(), vessel_count=len(features), breach_count=breach_count, features=features
    )
