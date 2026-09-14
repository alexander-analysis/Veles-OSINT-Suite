"""Sanctions tables.

``SanctionsEntity`` holds one row per *listing* - (authority, source_id) - so
OFAC, EU and UN entries for the same real-world entity stay separate and
auditable; "designated by" views are grouped at query time by normalised name.
``SanctionsUpdate`` is the change log produced by each list refresh and
``SanctionsProgramTracking`` keeps per-programme counts.
"""

from sqlalchemy import JSON, Boolean, Column, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship

from app.models.base import Base, utcnow


class SanctionsEntity(Base):
    """One designated entity (vessel, company, person, aircraft) from one authority."""

    __tablename__ = "sanctions_entities"

    id = Column(Integer, primary_key=True)
    designating_authority = Column(String(20), nullable=False, index=True)  # OFAC, EU, UN
    source_id = Column(String(50), nullable=False)  # authority's own identifier (ent_num, EU ref, DATAID)
    name = Column(String(300), nullable=False, index=True)
    name_normalized = Column(String(300), index=True)  # upper-case ASCII for matching
    entity_type = Column(String(50), index=True)  # vessel, company, person, aircraft
    un_committee = Column(String(50))  # UN list type (DPRK, Iran, ...)
    country_linked = Column(String(3))  # ISO country code
    designation_date = Column(DateTime)
    programs = Column(JSON)  # ["RUSSIA-EO14024", "IRAN", ...]
    addresses = Column(JSON)
    aliases = Column(JSON)  # alternate names / AKAs
    # Vessel-specific (OFAC vessel rows; IMO may also be an IMO *company* number on company rows)
    imo = Column(String(20), index=True)
    mmsi = Column(String(20), index=True)
    call_sign = Column(String(20))
    vessel_flag = Column(String(3))
    vessel_type = Column(String(100))
    vessel_owner = Column(String(300))
    remarks = Column(Text)  # justification / remarks from the source
    # Status tracking
    is_active = Column(Boolean, default=True, nullable=False, index=True)  # False = delisted
    delisting_date = Column(DateTime)
    first_seen_at = Column(DateTime, default=utcnow, nullable=False)
    last_updated = Column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)
    source_url = Column(String(500))

    breaches = relationship("SanctionsBreach", back_populates="sanctioned_entity")

    __table_args__ = (
        UniqueConstraint("designating_authority", "source_id", name="uq_sanctions_entities_authority_source"),
        Index("ix_sanctions_entities_name_authority", "name", "designating_authority"),
        Index("ix_sanctions_entities_active_type", "is_active", "entity_type"),
    )


class SanctionsUpdate(Base):
    """Change detected by a list refresh: new designation, delisting, or changed fields."""

    __tablename__ = "sanctions_updates"

    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime, nullable=False, default=utcnow, index=True)
    authority = Column(String(20), nullable=False, index=True)
    update_type = Column(String(50), nullable=False)  # new_designation, delisting, program_change, name_change, relisted
    entity_id = Column(Integer, ForeignKey("sanctions_entities.id"))
    entity_name = Column(String(300))
    entity_type = Column(String(50))
    previous_status = Column(JSON)
    new_status = Column(JSON)
    processed = Column(Boolean, default=False, nullable=False)  # alerts generated?
    alerts_generated = Column(Integer, default=0)
    source_url = Column(String(500))

    entity = relationship("SanctionsEntity")

    __table_args__ = (Index("ix_sanctions_updates_authority_timestamp", "authority", "timestamp"),)


class SanctionsProgramTracking(Base):
    """Per-authority / per-programme counts and refresh bookkeeping."""

    __tablename__ = "sanctions_program_tracking"

    id = Column(Integer, primary_key=True)
    authority = Column(String(20), nullable=False)
    program_name = Column(String(100), nullable=False)
    entities_in_program = Column(Integer, default=0)
    vessels_in_program = Column(Integer, default=0)
    last_updated = Column(DateTime, index=True)
    enabled = Column(Boolean, default=True, nullable=False)
    alert_on_new = Column(Boolean, default=True, nullable=False)

    __table_args__ = (UniqueConstraint("authority", "program_name", name="uq_sanctions_program_tracking_authority_program"),)
