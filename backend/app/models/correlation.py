"""Cross-bot correlation engine tables (ecosystem Part 4)."""

from sqlalchemy import JSON, Boolean, Column, DateTime, Float, Index, Integer, String, Text

from app.models.base import Base, utcnow


class SignalCorrelation(Base):
    """Two signals from different bots that coincide in time and share a topic / entity / place."""

    __tablename__ = "signal_correlations"

    id = Column(Integer, primary_key=True)
    signal_a_type = Column(String(50), nullable=False, index=True)  # market_alert, sanctions_breach, evasion_event, transshipment, geopolitical_event, blockchain_tx, corporate_change, dark_oil
    signal_a_id = Column(Integer, nullable=False)
    signal_a_summary = Column(String(300))
    signal_a_time = Column(DateTime, nullable=False)
    signal_b_type = Column(String(50), nullable=False, index=True)
    signal_b_id = Column(Integer, nullable=False)
    signal_b_summary = Column(String(300))
    signal_b_time = Column(DateTime, nullable=False)
    correlation_type = Column(String(50))  # market_geopolitical, maritime_sanctions, energy_market, blockchain_market, ...
    time_delta_minutes = Column(Integer)
    shared_keys = Column(JSON)  # countries / assets / entities / vessels in common
    confidence = Column(Float, index=True)
    rationale = Column(String(500))
    detected_at = Column(DateTime, default=utcnow, nullable=False, index=True)

    __table_args__ = (Index("ix_signal_correlations_pair", "signal_a_type", "signal_a_id", "signal_b_type", "signal_b_id", unique=True),)


class CompositeAlert(Base):
    """Three or more domains lighting up together inside the window - the multi-signal operation pattern."""

    __tablename__ = "composite_alerts"

    id = Column(Integer, primary_key=True)
    title = Column(String(300), nullable=False)
    domains = Column(JSON, nullable=False)  # ["market", "maritime", "geopolitical"]
    signals = Column(JSON, nullable=False)  # [{type, id, summary, time}]
    shared_keys = Column(JSON)
    window_start = Column(DateTime, nullable=False, index=True)
    window_end = Column(DateTime, nullable=False)
    confidence = Column(Float, index=True)
    severity = Column(String(20))
    intelligence_summary = Column(Text)
    acknowledged = Column(Boolean, default=False, nullable=False)
    acknowledged_by = Column(String(100))
    detected_at = Column(DateTime, default=utcnow, nullable=False, index=True)
    fingerprint = Column(String(64), unique=True)
