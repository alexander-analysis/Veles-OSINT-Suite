"""Maritime API schemas (GeoJSON for the map, profiles, boards, audit log)."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.common import APIModel

InvestigationStatus = Literal["flagged", "review", "investigating", "cleared", "escalated", "possible", "confirmed"]


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
    destination: str | None = None
    speed: float | None = None
    heading: float | None = None
    ais_status: str | None = None
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


class VesselSummary(APIModel):
    id: int
    mmsi: str
    imo: str | None = None
    name: str
    flag_state: str
    ship_type: str | None = None
    owner_name: str | None = None
    destination: str | None = None
    current_position_lat: float | None = None
    current_position_lon: float | None = None
    current_speed: float | None = None
    ais_status: str | None = None
    last_ais_update: datetime | None = None
    ais_source: str | None = None
    sanctioned_status: str | None = None
    risk_score: float | None = None
    last_port_name: str | None = None


class VesselListResponse(APIModel):
    total: int
    limit: int
    offset: int
    vessels: list[VesselSummary]


class BreachOut(APIModel):
    id: int
    vessel_id: int
    vessel_name: str
    mmsi: str | None = None
    imo: str | None = None
    flag: str | None = None
    breach_type: str
    sanctioning_authority: str
    sanctioned_entity: str = Field(validation_alias="sanctioned_entity_name")
    sanctioned_entity_id: int | None = None
    severity: str
    match_confidence: float | None = None
    location: dict[str, Any] | None = None
    detected_at: datetime = Field(validation_alias="timestamp")
    first_detected_at: datetime | None = None
    last_confirmed_at: datetime | None = None
    investigation_status: str | None = None
    supporting_evidence: dict[str, Any] | None = None
    analyst_notes: str | None = None


class BreachListResponse(APIModel):
    total: int
    filters: dict[str, Any]
    breaches: list[BreachOut]


class InvestigationUpdate(BaseModel):
    investigation_status: InvestigationStatus | None = None
    analyst_notes: str | None = Field(None, max_length=500)
    updated_by: str = Field("anonymous", max_length=100)


class EvasionOut(APIModel):
    id: int
    vessel_id: int
    mmsi: str | None = None
    vessel_name: str | None = None
    event_type: str
    severity: str
    confidence_score: float | None = None
    timestamp: datetime
    location_lat: float | None = None
    location_lon: float | None = None
    details: dict[str, Any] | None = None
    summary: str | None = None
    investigation_status: str | None = None


class TransshipmentOut(APIModel):
    id: int
    vessel_a: dict[str, Any]
    vessel_b: dict[str, Any]
    timestamp: datetime
    location: dict[str, float]
    proximity_meters: float | None = None
    duration_minutes: int | None = None
    confidence_score: float | None = None
    investigation_status: str | None = None
    supporting_evidence: dict[str, Any] | None = None
    analyst_notes: str | None = None


class PortCallOut(APIModel):
    id: int
    vessel_id: int
    mmsi: str | None = None
    vessel_name: str | None = None
    flag: str | None = None
    port_name: str
    port_code: str | None = None
    port_country: str | None = None
    is_sanctioned_facility: bool
    facility_risk_level: str | None = None
    arrival_time: datetime
    departure_time: datetime | None = None
    dwell_time_hours: float | None = None
    cargo_type_predicted: str | None = None
    flags_raised: list[str] | None = None


class LaneViolationOut(APIModel):
    id: int
    vessel_id: int
    mmsi: str | None = None
    vessel_name: str | None = None
    lane_name: str
    timestamp: datetime
    severity: str | None = None
    context: str | None = None
    reason_suspected: str | None = None


class AuditEntryOut(APIModel):
    id: int
    timestamp: datetime
    action_type: str
    user: str | None = Field(None, validation_alias="user_id")
    vessel_id: int | None = None
    breach_id: int | None = None
    sanctioned_entity_name: str | None = None
    sanctioning_authorities: list[str] | None = None
    rationale: str | None = None
    supporting_data: dict[str, Any] | None = None
    related_entities: Any | None = None
    classification_level: str | None = None
    source_systems: list[str] | None = None
    is_final: bool
    created_by: str | None = None


class AuditLogResponse(APIModel):
    total: int
    limit: int
    offset: int
    entries: list[AuditEntryOut]


class ExportRequest(BaseModel):
    format: Literal["json", "csv", "pdf"] = "json"
    start_date: datetime | None = None
    end_date: datetime | None = None
    action_type: str | None = None
    vessel_id: int | None = None
    classification: str = Field("UNCLASSIFIED", max_length=50)
    include_sections: list[str] = Field(default_factory=lambda: ["executive_summary", "breach_analysis", "audit_entries"])
    requested_by: str = Field("anonymous", max_length=100)
