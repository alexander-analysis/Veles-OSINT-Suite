"""Maritime-intelligence tables: vessels, positions, breaches, transshipments, port calls, lane violations."""

from sqlalchemy import JSON, Boolean, Column, DateTime, Float, ForeignKey, Index, Integer, String
from sqlalchemy.orm import relationship

from app.models.base import Base, TimestampMixin, UpdatedTimestampMixin, utcnow


class Vessel(UpdatedTimestampMixin, Base):
    """Ship master data plus a denormalised copy of the latest AIS fix."""

    __tablename__ = "vessels"

    id = Column(Integer, primary_key=True)
    mmsi = Column(String(20), unique=True, nullable=False, index=True)  # AIS transponder identity
    imo = Column(String(20), unique=True, nullable=True, index=True)  # hull identity (survives renames/reflags)
    name = Column(String(200), nullable=False, index=True)  # current vessel name
    historical_names = Column(JSON)  # previous names (name-spoofing detection)
    historical_flags = Column(JSON)  # previous flag states (re-flagging detection)
    destination = Column(String(100))  # AIS-declared destination
    call_sign = Column(String(20), index=True)
    flag_state = Column(String(3), nullable=False, index=True)  # ISO country code
    ship_type = Column(String(100))  # Tanker, Cargo, ...
    gross_tonnage = Column(Float)
    owner_name = Column(String(200), index=True)
    registered_operator = Column(String(200))
    beneficial_owner = Column(String(200))  # real owner (may differ from registered)
    last_port_name = Column(String(200))
    last_port_time = Column(DateTime)
    current_position_lat = Column(Float)
    current_position_lon = Column(Float)
    current_heading = Column(Float)
    current_speed = Column(Float)  # knots
    ais_status = Column(String(50))  # underway, moored, aground, ...
    last_ais_update = Column(DateTime, index=True)
    ais_source = Column(String(50))  # marinetraffic, rtl_sdr, ais_hub, satellite
    sanctioned_status = Column(String(50), index=True, default="clear")  # clear, flagged, breach_ofac, breach_eu, breach_un
    risk_score = Column(Float)  # composite risk 0.0-1.0

    positions = relationship("VesselPosition", back_populates="vessel", cascade="all, delete-orphan")
    breaches = relationship("SanctionsBreach", back_populates="vessel")
    port_calls = relationship("PortCallEvent", back_populates="vessel")

    __table_args__ = (
        Index("ix_vessels_mmsi_sanctioned", "mmsi", "sanctioned_status"),
        Index("ix_vessels_owner_risk", "owner_name", "risk_score"),
    )


class VesselPosition(TimestampMixin, Base):
    """Real-time and historical vessel positions."""

    __tablename__ = "vessel_positions"

    id = Column(Integer, primary_key=True)
    vessel_id = Column(Integer, ForeignKey("vessels.id"), nullable=False, index=True)
    mmsi = Column(String(20), index=True)  # denormalised for fast lookup
    timestamp = Column(DateTime, nullable=False, index=True)  # UTC time of the fix
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    heading = Column(Float)  # compass heading 0-360
    speed = Column(Float)  # knots
    course = Column(Float)  # course over ground
    ais_source = Column(String(50))  # which source provided this fix
    signal_quality = Column(Integer)  # 0-100

    vessel = relationship("Vessel", back_populates="positions")

    __table_args__ = (
        Index("ix_vessel_positions_mmsi_timestamp", "mmsi", "timestamp"),
        Index("ix_vessel_positions_vessel_timestamp", "vessel_id", "timestamp"),
    )


class SanctionsBreach(Base):
    """A vessel matched against a designated entity."""

    __tablename__ = "sanctions_breaches"

    id = Column(Integer, primary_key=True)
    vessel_id = Column(Integer, ForeignKey("vessels.id"), nullable=False, index=True)
    vessel_name = Column(String(200), nullable=False)
    mmsi = Column(String(20), index=True)
    imo = Column(String(20))
    flag = Column(String(3))
    breach_type = Column(String(50), nullable=False)  # direct_match, owner_match, flag_violation, transshipment, evasion
    sanctioning_authority = Column(String(20), nullable=False, index=True)  # OFAC, EU, UN
    sanctioned_entity_name = Column(String(300), nullable=False)
    sanctioned_entity_id = Column(Integer, ForeignKey("sanctions_entities.id"), index=True)
    match_confidence = Column(Float)  # 0.0-1.0
    severity = Column(String(20), nullable=False, index=True)  # critical, high, medium
    location_lat = Column(Float)
    location_lon = Column(Float)
    location_description = Column(String(200))
    timestamp = Column(DateTime, nullable=False, index=True, default=utcnow)  # when detected
    first_detected_at = Column(DateTime, default=utcnow, nullable=False)
    last_confirmed_at = Column(DateTime, onupdate=utcnow)
    investigation_status = Column(String(50), index=True, default="flagged")  # flagged, investigating, cleared, escalated
    supporting_evidence = Column(JSON)  # links to related data
    analyst_notes = Column(String(500))

    vessel = relationship("Vessel", back_populates="breaches")
    sanctioned_entity = relationship("SanctionsEntity", back_populates="breaches")
    audit_entries = relationship("AuditLog", back_populates="breach")

    __table_args__ = (
        Index("ix_sanctions_breaches_vessel_authority", "vessel_id", "sanctioning_authority"),
        Index("ix_sanctions_breaches_status_severity", "investigation_status", "severity"),
    )


class TransshipmentEvent(Base):
    """Detected ship-to-ship transfer (two vessels loitering in close proximity)."""

    __tablename__ = "transshipment_events"

    id = Column(Integer, primary_key=True)
    vessel_a_id = Column(Integer, ForeignKey("vessels.id"), nullable=False)
    vessel_b_id = Column(Integer, ForeignKey("vessels.id"), nullable=False)
    vessel_a_mmsi = Column(String(20))
    vessel_b_mmsi = Column(String(20))
    timestamp = Column(DateTime, nullable=False, index=True)  # when the transfer was detected
    location_lat = Column(Float, nullable=False)
    location_lon = Column(Float, nullable=False)
    proximity_meters = Column(Float)
    duration_minutes = Column(Integer)
    confidence_score = Column(Float)  # 0.0-1.0 probability of an actual transfer
    detected_at = Column(DateTime, default=utcnow, nullable=False)
    investigation_status = Column(String(50), default="possible")  # possible, confirmed, cleared
    supporting_evidence = Column(JSON)  # related position data, timing
    analyst_notes = Column(String(500))

    vessel_a = relationship("Vessel", foreign_keys=[vessel_a_id])
    vessel_b = relationship("Vessel", foreign_keys=[vessel_b_id])

    __table_args__ = (Index("ix_transshipment_events_vessels_timestamp", "vessel_a_id", "vessel_b_id", "timestamp"),)


class PortCallEvent(TimestampMixin, Base):
    """Vessel port visits."""

    __tablename__ = "port_call_events"

    id = Column(Integer, primary_key=True)
    vessel_id = Column(Integer, ForeignKey("vessels.id"), nullable=False, index=True)
    mmsi = Column(String(20), index=True)
    port_name = Column(String(200), nullable=False, index=True)
    port_code = Column(String(20))  # UN/LOCODE
    port_country = Column(String(3))  # ISO country code
    is_sanctioned_facility = Column(Boolean, default=False, nullable=False, index=True)
    facility_risk_level = Column(String(50))  # safe, medium, high
    arrival_time = Column(DateTime, nullable=False)
    departure_time = Column(DateTime)
    dwell_time_hours = Column(Float)
    cargo_type_predicted = Column(String(200))  # inferred from vessel type / route
    flags_raised = Column(JSON)  # anomalies detected (unusual dwell, ...)

    vessel = relationship("Vessel", back_populates="port_calls")

    __table_args__ = (Index("ix_port_call_events_vessel_port_time", "vessel_id", "port_name", "arrival_time"),)


class ShippingLaneViolation(Base):
    """Vessel deviation from a defined shipping lane."""

    __tablename__ = "shipping_lane_violations"

    id = Column(Integer, primary_key=True)
    vessel_id = Column(Integer, ForeignKey("vessels.id"), nullable=False, index=True)
    mmsi = Column(String(20), index=True)
    lane_name = Column(String(200), nullable=False)  # Suez Canal, Strait of Hormuz, ...
    deviation_distance_nm = Column(Float)  # nautical miles from the lane
    timestamp = Column(DateTime, nullable=False, index=True)
    severity = Column(String(50))  # low, medium, high
    context = Column(String(200))  # war_zone, sanctions_zone, piracy_zone
    reason_suspected = Column(String(300))  # analyst hypothesis
    detected_at = Column(DateTime, default=utcnow, nullable=False)

    __table_args__ = (Index("ix_shipping_lane_violations_vessel_lane", "vessel_id", "lane_name"),)


class EvasionEvent(Base):
    """Sanctions-evasion indicator: AIS gap, flag change, name change, identity conflict, dark in zone."""

    __tablename__ = "evasion_events"

    id = Column(Integer, primary_key=True)
    vessel_id = Column(Integer, ForeignKey("vessels.id"), nullable=False, index=True)
    mmsi = Column(String(20), index=True)
    event_type = Column(String(50), nullable=False, index=True)  # ais_gap, flag_change, name_change, identity_conflict, dark_in_zone
    severity = Column(String(20), nullable=False)  # low, medium, high, critical
    confidence_score = Column(Float)
    timestamp = Column(DateTime, nullable=False, index=True)
    location_lat = Column(Float)
    location_lon = Column(Float)
    details = Column(JSON)  # gap hours, old/new values, zone name, ...
    summary = Column(String(300))
    investigation_status = Column(String(50), default="flagged")
    analyst_notes = Column(String(500))
    created_at = Column(DateTime, default=utcnow, nullable=False)

    vessel = relationship("Vessel")

    __table_args__ = (Index("ix_evasion_events_vessel_type_time", "vessel_id", "event_type", "timestamp"),)
