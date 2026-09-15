"""Energy flow monitor API schemas."""

from datetime import datetime
from typing import Any

from app.schemas.common import APIModel


class FacilityOut(APIModel):
    id: int
    facility_name: str
    facility_type: str | None = None
    country: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    radius_km: float | None = None
    commodity: str | None = None
    production_capacity_bpd: float | None = None
    production_capacity_mtpa: float | None = None
    operator_name: str | None = None
    owner_name: str | None = None
    owner_sanctioned: bool = False
    is_sanctioned_facility: bool = False
    sanctioning_authority: str | None = None
    notes: str | None = None
    tanker_calls_7d: int | None = None
    tanker_calls_30d: int | None = None
    estimated_utilization: float | None = None
    last_activity_at: datetime | None = None


class ShipmentOut(APIModel):
    id: int
    vessel_id: int
    vessel_name: str | None = None
    mmsi: str | None = None
    imo: str | None = None
    flag: str | None = None
    cargo_type: str | None = None
    cargo_volume_barrels: float | None = None
    origin_country: str | None = None
    destination_country: str | None = None
    loading_facility_id: int | None = None
    loading_location: str | None = None
    loading_date: datetime | None = None
    discharge_facility_id: int | None = None
    discharge_location: str | None = None
    discharge_date: datetime | None = None
    draught_departure: float | None = None
    draught_arrival: float | None = None
    laden: bool | None = None
    sanctioned_route: bool = False
    dark_oil_suspect: bool = False
    transshipment_suspect: bool = False
    status: str | None = None
    risk_score: float | None = None
    evidence: dict[str, Any] | None = None
    created_at: datetime


class ShipmentsResponse(APIModel):
    total: int
    limit: int
    filters: dict[str, Any]
    shipments: list[ShipmentOut]


class DarkOilOut(APIModel):
    id: int
    tanker_id: int
    tanker_name: str | None = None
    mmsi: str | None = None
    detected_pattern: str | None = None
    suspected_origin: str | None = None
    suspected_destination: str | None = None
    evidence: dict[str, Any] | None = None
    confidence_score: float | None = None
    severity: str | None = None
    summary: str | None = None
    shipment_id: int | None = None
    detected_at: datetime
    voyage_start: datetime | None = None
    investigation_status: str | None = None


class DarkOilResponse(APIModel):
    total: int
    limit: int
    filters: dict[str, Any]
    indicators: list[DarkOilOut]


class FlowPoint(APIModel):
    day: datetime
    facility_id: int
    tanker_arrivals: int | None = None
    tanker_departures: int | None = None
    laden_departures: int | None = None
    estimated_barrels: float | None = None
    flagged_tankers: int | None = None


class FlowsResponse(APIModel):
    days: int
    facility_id: int | None = None
    country: str | None = None
    points: list[FlowPoint]


class FacilityDetail(APIModel):
    facility: FacilityOut
    recent_calls: list[dict[str, Any]]
    shipments: list[ShipmentOut]
    flows: list[FlowPoint]
