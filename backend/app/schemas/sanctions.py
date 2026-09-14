"""Sanctions API schemas."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.common import APIModel


class SanctionsEntityOut(APIModel):
    id: int
    designating_authority: str
    designating_authorities: list[str] = Field(default_factory=list, description="All authorities with an active listing of this name")
    source_id: str
    name: str
    entity_type: str | None = None
    programs: list[str] | None = None
    aliases: list[str] | None = None
    addresses: list[str] | None = None
    country_linked: str | None = None
    un_committee: str | None = None
    designation_date: datetime | None = None
    imo: str | None = None
    mmsi: str | None = None
    call_sign: str | None = None
    vessel_flag: str | None = None
    vessel_type: str | None = None
    vessel_owner: str | None = None
    remarks: str | None = None
    is_active: bool
    delisting_date: datetime | None = None
    last_updated: datetime
    source_url: str | None = None


class EntitySearchResponse(APIModel):
    query: str | None = None
    filters: dict[str, Any]
    total: int
    limit: int
    offset: int
    entities: list[SanctionsEntityOut]


class MatchOut(APIModel):
    authority: str
    entity_id: int | None = None
    official_name: str | None = None
    entity_type: str | None = None
    match_type: str
    matched_value: str
    similarity: float | None = None
    confidence: float
    severity: str
    breach_type: str
    programs: list[str] = []
    designation_date: datetime | None = None
    summary: str


class CheckEntityRequest(BaseModel):
    entity_name: str = Field(..., min_length=2, max_length=300)
    entity_type: str | None = Field(None, description="vessel, company, person, aircraft")
    check_aliases: bool = True
    min_similarity: float = Field(0.85, ge=0.5, le=1.0)
    requested_by: str = Field("anonymous", max_length=100)


class CheckEntityResponse(APIModel):
    entity_name: str
    is_sanctioned: bool
    confidence: float
    designating_authorities: list[str]
    sanctions_programs: list[str]
    matching_entries: list[MatchOut]


class VesselSanctionsResponse(APIModel):
    mmsi: str
    vessel_name: str | None = None
    imo: str | None = None
    flag: str | None = None
    owner: str | None = None
    sanctions_status: str
    risk_score: float | None = None
    recorded_breaches: list[dict[str, Any]]
    live_matches: list[MatchOut]
    programs_active: list[str]
    recommendation: str


class SanctionsUpdateOut(APIModel):
    id: int
    timestamp: datetime
    authority: str
    update_type: str
    entity_id: int | None = None
    entity_name: str | None = None
    entity_type: str | None = None
    previous_status: dict[str, Any] | None = None
    new_status: dict[str, Any] | None = None
    source_url: str | None = None


class UpdatesResponse(APIModel):
    timeframe_days: int
    period: str
    total_updates: int
    summary: dict[str, dict[str, int]]
    updates: list[SanctionsUpdateOut]


class ProgramOut(APIModel):
    authority: str
    program: str = Field(validation_alias="program_name")
    entities_count: int = Field(validation_alias="entities_in_program")
    vessels_count: int = Field(validation_alias="vessels_in_program")
    last_updated: datetime | None = None
    enabled: bool
    alert_on_new: bool


class ProgramsResponse(APIModel):
    programs: list[ProgramOut]
    totals: dict[str, int]
