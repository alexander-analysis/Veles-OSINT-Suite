"""Corporate intelligence API schemas."""

from datetime import datetime
from typing import Any

from pydantic import Field

from app.schemas.common import APIModel


class CompanyOut(APIModel):
    id: int
    company_name: str
    lei: str | None = None
    registration_number: str | None = None
    registration_authority: str | None = None
    registration_country: str | None = None
    registration_date: datetime | None = None
    company_type: str | None = None
    entity_category: str | None = None
    entity_status: str | None = None
    registration_status: str | None = None
    industry_sector: str | None = None
    registered_address: str | None = None
    business_address: str | None = None
    website: str | None = None
    source: str | None = None
    source_ref: str | None = None
    is_shell_company: bool = False
    shell_company_confidence: float | None = None
    shell_indicators: list[str] | None = None
    risk_score: float | None = None
    linked_to_sanctioned: bool = False
    sanctioned_entity_id: int | None = None
    sanctions_match_type: str | None = None
    sanctions_confidence: float | None = None
    ownership_opaque: bool = False
    parent_reporting_exception: str | None = None
    is_active: bool = True
    origin: str | None = None
    last_enriched: datetime | None = None
    updated_at: datetime


class CompaniesResponse(APIModel):
    total: int
    limit: int
    offset: int
    filters: dict[str, Any]
    companies: list[CompanyOut]


class ShareholderOut(APIModel):
    id: int
    shareholder_name: str
    shareholder_type: str | None = None
    relationship_type: str | None = None
    share_percentage: float | None = None
    shareholder_company_id: int | None = None
    shareholder_lei: str | None = None
    country: str | None = None
    is_sanctioned: bool = False
    sanctioned_entity_id: int | None = None
    is_beneficial_owner: bool = False
    source: str | None = None


class DirectorOut(APIModel):
    id: int
    name: str
    title: str | None = None
    nationality: str | None = None
    is_sanctioned: bool = False
    appointment_date: datetime | None = None
    resignation_date: datetime | None = None
    red_flag_director: bool = False
    source: str | None = None


class OwnershipChainOut(APIModel):
    id: int
    subsidiary_id: int
    subsidiary_name: str | None = None
    ultimate_owner_name: str | None = None
    ultimate_owner_type: str | None = None
    ultimate_owner_lei: str | None = None
    ultimate_owner_country: str | None = None
    chain_length: int | None = None
    chain_path: list[dict[str, Any]] | None = None
    involves_sanctioned: bool = False
    involves_shell_companies: bool = False
    involves_secrecy_jurisdiction: bool = False
    risk_score: float | None = None
    computed_at: datetime


class RelatedCompany(APIModel):
    id: int
    company_name: str
    lei: str | None = None
    registration_country: str | None = None
    relationship: str
    linked_to_sanctioned: bool = False
    sanctions_match_type: str | None = None
    risk_score: float | None = None


class SanctionedRef(APIModel):
    id: int
    name: str
    designating_authority: str
    programs: list[str] | None = None
    entity_type: str | None = None


class CompanyDetail(APIModel):
    company: CompanyOut
    shareholders: list[ShareholderOut]
    directors: list[DirectorOut]
    subsidiaries: list[RelatedCompany]
    parents: list[RelatedCompany]
    ownership_chain: OwnershipChainOut | None = None
    sanctioned_entity: SanctionedRef | None = None
    gleif_url: str | None = None


class LeiSearchHit(APIModel):
    lei: str
    name: str
    other_names: list[str] = Field(default_factory=list)
    country: str | None = None
    jurisdiction: str | None = None
    status: str | None = None
    registration_status: str | None = None
    category: str | None = None
    creation_date: datetime | None = None
    city: str | None = None
    tracked_company_id: int | None = None
    sanctions_hits: int = 0


class LeiSearchResponse(APIModel):
    query: str
    live: bool
    hits: list[LeiSearchHit]


class IngestRequest(APIModel):
    lei: str = Field(min_length=20, max_length=20)
    analyst: str | None = Field(None, max_length=100)
