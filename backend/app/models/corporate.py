"""Corporate intelligence tables (ecosystem bot 6)."""

from sqlalchemy import JSON, Boolean, Column, DateTime, Float, ForeignKey, Index, Integer, String
from sqlalchemy.orm import relationship

from app.models.base import Base, utcnow


class Company(Base):
    """A legal entity from GLEIF, EDGAR, Companies House or an analyst search."""

    __tablename__ = "companies"

    id = Column(Integer, primary_key=True)
    company_name = Column(String(300), nullable=False, index=True)
    name_normalized = Column(String(300), index=True)
    lei = Column(String(20), unique=True, index=True)  # Legal Entity Identifier (GLEIF)
    registration_number = Column(String(100), index=True)
    registration_authority = Column(String(100))
    registration_country = Column(String(3), index=True)
    registration_date = Column(DateTime)
    company_type = Column(String(150))  # legal form
    entity_category = Column(String(50))  # GENERAL, FUND, BRANCH, ...
    entity_status = Column(String(30))  # ACTIVE, INACTIVE
    registration_status = Column(String(30))  # ISSUED, LAPSED, RETIRED
    industry_sector = Column(String(100))
    registered_address = Column(String(500))
    business_address = Column(String(500))
    website = Column(String(300))
    source = Column(String(50))  # gleif, edgar, companies_house, opencorporates, manual
    source_ref = Column(String(120))  # CIK, company number, ...
    is_shell_company = Column(Boolean, default=False, nullable=False, index=True)
    shell_company_confidence = Column(Float)
    shell_indicators = Column(JSON)
    risk_score = Column(Float, index=True)
    linked_to_sanctioned = Column(Boolean, default=False, nullable=False, index=True)
    sanctioned_entity_id = Column(Integer, ForeignKey("sanctions_entities.id"), index=True)
    sanctions_match_type = Column(String(50))  # direct, parent, child, director, shareholder
    sanctions_confidence = Column(Float)
    ownership_opaque = Column(Boolean, default=False, nullable=False)  # parent undisclosed / reporting exception
    parent_reporting_exception = Column(String(60))
    is_active = Column(Boolean, default=True, nullable=False)
    dissolution_date = Column(DateTime)
    origin = Column(String(50))  # why we hold it: sanctions_seed, vessel_owner, analyst_search, ownership_walk, new_formation
    last_enriched = Column(DateTime)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    directors = relationship("CompanyDirector", back_populates="company", cascade="all, delete-orphan")
    shareholders = relationship("Shareholder", back_populates="company", cascade="all, delete-orphan", foreign_keys="Shareholder.company_id")
    sanctioned_entity = relationship("SanctionsEntity")

    __table_args__ = (Index("ix_companies_name_country", "company_name", "registration_country"),)


class CompanyDirector(Base):
    """Officer / director / person with significant control."""

    __tablename__ = "company_directors"

    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    name = Column(String(200), nullable=False, index=True)
    name_normalized = Column(String(200), index=True)
    title = Column(String(100))
    nationality = Column(String(3))
    country_of_residence = Column(String(3))
    date_of_birth = Column(String(20))  # month/year granularity from registries
    is_sanctioned = Column(Boolean, default=False, nullable=False, index=True)
    sanctioned_entity_id = Column(Integer, ForeignKey("sanctions_entities.id"))
    appointment_date = Column(DateTime)
    resignation_date = Column(DateTime)
    red_flag_director = Column(Boolean, default=False, nullable=False)
    other_appointments = Column(Integer)
    source = Column(String(50))

    company = relationship("Company", back_populates="directors")


class Shareholder(Base):
    """Shareholder / parent / controlling party."""

    __tablename__ = "shareholders"

    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    shareholder_name = Column(String(300), nullable=False, index=True)
    shareholder_type = Column(String(50))  # individual, company, trust, state
    relationship_type = Column(String(50))  # direct_parent, ultimate_parent, psc, shareholder
    share_percentage = Column(Float)
    share_count = Column(Integer)
    shareholder_company_id = Column(Integer, ForeignKey("companies.id"), index=True)
    shareholder_lei = Column(String(20))
    country = Column(String(3))
    is_sanctioned = Column(Boolean, default=False, nullable=False, index=True)
    sanctioned_entity_id = Column(Integer, ForeignKey("sanctions_entities.id"))
    is_beneficial_owner = Column(Boolean, default=False, nullable=False)
    source = Column(String(50))
    created_at = Column(DateTime, default=utcnow, nullable=False)

    company = relationship("Company", back_populates="shareholders", foreign_keys=[company_id])
    shareholder_company = relationship("Company", foreign_keys=[shareholder_company_id])


class OwnershipChain(Base):
    """Traced ownership path from a company to its ultimate parent / beneficial owner."""

    __tablename__ = "ownership_chains"

    id = Column(Integer, primary_key=True)
    subsidiary_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    subsidiary_name = Column(String(300))
    ultimate_owner_name = Column(String(300), index=True)
    ultimate_owner_type = Column(String(50))
    ultimate_owner_lei = Column(String(20))
    ultimate_owner_country = Column(String(3))
    chain_length = Column(Integer)
    chain_path = Column(JSON)  # [{name, lei, country, relationship}]
    involves_sanctioned = Column(Boolean, default=False, nullable=False, index=True)
    involves_shell_companies = Column(Boolean, default=False, nullable=False)
    involves_secrecy_jurisdiction = Column(Boolean, default=False, nullable=False)
    risk_score = Column(Float)
    computed_at = Column(DateTime, default=utcnow, nullable=False)

    subsidiary = relationship("Company", foreign_keys=[subsidiary_id])
