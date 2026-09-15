"""Ecosystem tier 2 / 3 tables: aviation, leaks & breaches, narratives, domain / IP assets, legal events."""

from sqlalchemy import JSON, Boolean, Column, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import relationship

from app.models.base import Base, utcnow


class Aircraft(Base):
    """A sanctioned or watched airframe (OFAC aircraft listings carry the registration, model, operator, MSN)."""

    __tablename__ = "aircraft"

    id = Column(Integer, primary_key=True)
    registration = Column(String(20), unique=True, nullable=False, index=True)
    icao_hex = Column(String(10), index=True)  # Mode S transponder code, learned from ADS-B sightings or the listing
    model = Column(String(100))
    operator = Column(String(200), index=True)
    owner = Column(String(200))
    manufacturer_serial = Column(String(60))
    country = Column(String(3), index=True)  # from the registration prefix
    is_sanctioned = Column(Boolean, default=False, nullable=False, index=True)
    sanctioned_entity_id = Column(Integer, ForeignKey("sanctions_entities.id"), index=True)
    sanctioning_authority = Column(String(20))
    programs = Column(JSON)
    watch = Column(Boolean, default=True, nullable=False)
    origin = Column(String(50))  # sanctions_seed, analyst
    notes = Column(String(500))
    last_seen = Column(DateTime, index=True)
    last_lat = Column(Float)
    last_lon = Column(Float)
    last_altitude_ft = Column(Float)
    last_callsign = Column(String(20))
    last_checked = Column(DateTime, index=True)
    sightings_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=utcnow, nullable=False)

    entity = relationship("SanctionsEntity")


class AircraftSighting(Base):
    __tablename__ = "aircraft_sightings"

    id = Column(Integer, primary_key=True)
    aircraft_id = Column(Integer, ForeignKey("aircraft.id"), nullable=False, index=True)
    registration = Column(String(20), index=True)
    icao_hex = Column(String(10))
    timestamp = Column(DateTime, nullable=False, index=True)
    latitude = Column(Float)
    longitude = Column(Float)
    altitude_ft = Column(Float)
    ground_speed_kts = Column(Float)
    heading = Column(Float)
    callsign = Column(String(20))
    squawk = Column(String(10))
    on_ground = Column(Boolean)
    source = Column(String(30))  # adsb_lol, opensky
    nearest_country = Column(String(3))
    nearest_place = Column(String(120))
    flight_key = Column(String(60), index=True)  # registration + day + callsign - groups sightings into flights
    details = Column(JSON)

    aircraft = relationship("Aircraft")

    __table_args__ = (Index("ix_aircraft_sightings_aircraft_time", "aircraft_id", "timestamp"),)


class BreachEvent(Base):
    """Ransomware victim postings and public breach records matched against tracked companies / sectors."""

    __tablename__ = "breach_events"

    id = Column(Integer, primary_key=True)
    source = Column(String(30), nullable=False, index=True)  # ransomware_live, hibp
    source_id = Column(String(200), nullable=False)
    victim_name = Column(String(300), nullable=False, index=True)
    victim_domain = Column(String(200))
    country = Column(String(3), index=True)
    sector = Column(String(100), index=True)
    threat_actor = Column(String(100), index=True)
    event_date = Column(DateTime, index=True)
    discovered_at = Column(DateTime, default=utcnow, nullable=False, index=True)
    description = Column(Text)
    url = Column(String(500))
    records_affected = Column(Integer)
    data_classes = Column(JSON)
    matched_company_id = Column(Integer, ForeignKey("companies.id"), index=True)
    matched_entity_id = Column(Integer, ForeignKey("sanctions_entities.id"))
    relevance = Column(String(30), index=True)  # tracked_company, sanctioned_party, critical_sector, watch_keyword, general
    relevance_score = Column(Float, index=True)
    severity = Column(String(20))
    details = Column(JSON)

    __table_args__ = (Index("ix_breach_events_source_ref", "source", "source_id", unique=True),)


class Narrative(Base):
    """A story pushed across state-media outlets inside a short window (framing / disinformation watch)."""

    __tablename__ = "narratives"

    id = Column(Integer, primary_key=True)
    fingerprint = Column(String(64), unique=True, nullable=False)
    topic = Column(String(300), nullable=False)
    keywords = Column(JSON)
    outlets = Column(JSON)  # {"rt": 3, "tass": 2}
    outlet_count = Column(Integer)
    item_count = Column(Integer)
    countries = Column(JSON)
    sample_titles = Column(JSON)
    sample_urls = Column(JSON)
    first_seen = Column(DateTime, index=True)
    last_seen = Column(DateTime, index=True)
    western_coverage = Column(Integer)  # matching non-state items in the same window (0 = state media only)
    divergence = Column(String(30))  # state_only, amplified, mirrored
    score = Column(Float, index=True)
    severity = Column(String(20))
    assessment = Column(String(500))
    detected_at = Column(DateTime, default=utcnow, nullable=False)


class InfraAsset(Base):
    """Domains and IPs tied to listed parties (from OFAC 'Website' remarks) and their resolution / certificate footprint."""

    __tablename__ = "infra_assets"

    id = Column(Integer, primary_key=True)
    asset_type = Column(String(20), nullable=False, index=True)  # domain, ip
    value = Column(String(255), nullable=False, index=True)
    entity_id = Column(Integer, ForeignKey("sanctions_entities.id"), index=True)
    entity_name = Column(String(300), index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), index=True)
    registrar = Column(String(200))
    registered_at = Column(DateTime)
    expires_at = Column(DateTime)
    nameservers = Column(JSON)
    resolves_to = Column(JSON)  # IPs
    asn = Column(String(30))
    asn_org = Column(String(200))
    hosting_country = Column(String(3), index=True)
    certificate_count = Column(Integer)
    certificate_names = Column(JSON)  # subdomains seen in CT logs
    is_live = Column(Boolean)
    findings = Column(JSON)
    risk_score = Column(Float)
    last_checked = Column(DateTime, index=True)
    created_at = Column(DateTime, default=utcnow, nullable=False)

    __table_args__ = (Index("ix_infra_assets_type_value", "asset_type", "value", unique=True),)


class LegalEvent(Base):
    """Court dockets, enforcement actions and prosecutions that name a tracked party."""

    __tablename__ = "legal_events"

    id = Column(Integer, primary_key=True)
    source = Column(String(30), nullable=False, index=True)  # courtlistener, ofac_enforcement, doj
    source_id = Column(String(200), nullable=False)
    title = Column(String(500), nullable=False)
    url = Column(String(500))
    court = Column(String(200))
    event_date = Column(DateTime, index=True)
    discovered_at = Column(DateTime, default=utcnow, nullable=False, index=True)
    event_type = Column(String(50), index=True)  # docket, opinion, enforcement, indictment, settlement
    matched_entity_id = Column(Integer, ForeignKey("sanctions_entities.id"), index=True)
    matched_entity_name = Column(String(300), index=True)
    matched_company_id = Column(Integer, ForeignKey("companies.id"))
    query_used = Column(String(300))
    summary = Column(Text)
    penalty_usd = Column(Float)
    relevance_score = Column(Float)
    details = Column(JSON)

    __table_args__ = (Index("ix_legal_events_source_ref", "source", "source_id", unique=True),)
