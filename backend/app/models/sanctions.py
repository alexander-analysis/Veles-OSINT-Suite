"""Designated entities imported from the OFAC, EU and UN sanctions lists."""

from sqlalchemy import JSON, Column, DateTime, Index, Integer, String

from app.models.base import Base, utcnow


class SanctionsEntity(Base):
    """One designated entity (vessel, company or person) from one authority."""

    __tablename__ = "sanctions_entities"

    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False, index=True)
    entity_type = Column(String(50))  # vessel, company, person
    designating_authority = Column(String(20), nullable=False, index=True)  # OFAC, EU, UN
    un_committee = Column(String(50))  # if UN: which committee
    country_linked = Column(String(3))  # ISO country code
    designation_date = Column(DateTime)
    programs = Column(JSON)  # ["RUSSIA-EO14024", "IRAN", ...]
    addresses = Column(JSON)  # known addresses
    aliases = Column(JSON)  # known alternate names / AKAs
    imo = Column(String(20), index=True)  # vessel IMO number when the list provides it
    last_updated = Column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)
    source_url = Column(String(500))  # link to the authoritative source

    __table_args__ = (Index("ix_sanctions_entities_name_authority", "name", "designating_authority"),)
