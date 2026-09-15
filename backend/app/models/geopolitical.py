"""Geopolitical event monitor tables (ecosystem bot 4)."""

from sqlalchemy import JSON, Boolean, Column, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import relationship

from app.models.base import Base, utcnow


class GeopoliticalEvent(Base):
    """Global events: conflicts, sanctions actions, political changes, trade disputes, port/infrastructure disruptions."""

    __tablename__ = "geopolitical_events"

    id = Column(Integer, primary_key=True)
    event_type = Column(String(50), nullable=False, index=True)  # conflict, sanctions, political, trade, port_closure, infrastructure, maritime_incident
    title = Column(String(300), nullable=False)
    description = Column(Text)
    country_primary = Column(String(3), index=True)  # ISO alpha-2
    country_secondary = Column(String(3), index=True)
    region = Column(String(100))
    coordinates_lat = Column(Float)
    coordinates_lon = Column(Float)
    event_date = Column(DateTime, nullable=False, index=True)
    detected_date = Column(DateTime, default=utcnow, nullable=False, index=True)
    severity = Column(String(20), index=True)  # low, medium, high, critical
    source = Column(String(100))  # gdelt_events, gdelt_doc, gov_uk, un_press, ofac_recent_actions, ...
    source_id = Column(String(120), index=True)  # provider identifier for de-duplication
    source_urls = Column(JSON)
    verification_status = Column(String(50), default="unconfirmed")  # unconfirmed, confirmed, disputed
    confidence_score = Column(Float)
    keywords = Column(JSON)
    affected_sectors = Column(JSON)  # energy, finance, shipping, ...
    affected_countries = Column(JSON)
    goldstein_scale = Column(Float)  # GDELT conflict/cooperation scale (-10..10)
    mentions = Column(Integer)  # media mentions / articles
    correlated_with_market = Column(Boolean, default=False, nullable=False, index=True)
    correlated_with_maritime = Column(Boolean, default=False, nullable=False, index=True)
    correlated_with_sanctions = Column(Boolean, default=False, nullable=False, index=True)
    market_impact = Column(String(300))
    supply_chain_impact = Column(String(300))
    intelligence_notes = Column(Text)

    correlations = relationship("EventCorrelation", back_populates="event", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_geopolitical_events_type_date", "event_type", "event_date"),
        Index("ix_geopolitical_events_country_date", "country_primary", "event_date"),
        Index("ix_geopolitical_events_severity_date", "severity", "event_date"),
        Index("ix_geopolitical_events_source_ref", "source", "source_id"),
    )


class EventCorrelation(Base):
    """Link between a geopolitical event and a market / maritime / sanctions signal."""

    __tablename__ = "event_correlations"

    id = Column(Integer, primary_key=True)
    geopolitical_event_id = Column(Integer, ForeignKey("geopolitical_events.id"), nullable=False, index=True)
    event_type = Column(String(50))
    event_date = Column(DateTime)
    alert_type = Column(String(50), nullable=False)  # market_alert, sanctions_breach, evasion_event, transshipment, sanctions_update
    alert_id = Column(Integer, nullable=False)
    alert_timestamp = Column(DateTime, nullable=False, index=True)
    alert_summary = Column(String(300))
    time_delta_minutes = Column(Integer)
    time_delta_direction = Column(String(20))  # before, after, simultaneous
    correlation_score = Column(Float)
    correlation_type = Column(String(50))  # temporal, topical, entity, geographic
    intelligence_analysis = Column(Text)
    detected_at = Column(DateTime, default=utcnow, nullable=False)

    event = relationship("GeopoliticalEvent", back_populates="correlations")

    __table_args__ = (
        Index("ix_event_correlations_event_alert", "geopolitical_event_id", "alert_timestamp"),
        Index("ix_event_correlations_alert", "alert_type", "alert_id"),
    )


class NewsSource(Base):
    """Configured news / official information sources (credentials stay in .env, never here)."""

    __tablename__ = "news_sources"

    id = Column(Integer, primary_key=True)
    source_name = Column(String(100), unique=True, nullable=False)
    source_url = Column(String(500))
    source_type = Column(String(50))  # news, government, database, state_media
    categories = Column(JSON)
    enabled = Column(Boolean, default=True, nullable=False)
    last_fetch = Column(DateTime)
    last_status = Column(String(200))
    items_total = Column(Integer, default=0)
    reliability_score = Column(Float)  # 0-1 analyst-assessed
    latency_seconds = Column(Integer)
