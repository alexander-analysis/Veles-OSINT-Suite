"""Energy flow monitor tables (ecosystem bot 7)."""

from sqlalchemy import JSON, Boolean, Column, DateTime, Float, ForeignKey, Index, Integer, String
from sqlalchemy.orm import relationship

from app.models.base import Base, utcnow


class EnergyFacility(Base):
    """Export/import terminals, refineries, LNG plants and STS hubs relevant to sanctioned flows."""

    __tablename__ = "energy_facilities"

    id = Column(Integer, primary_key=True)
    facility_name = Column(String(300), nullable=False, index=True)
    facility_type = Column(String(50), index=True)  # crude_export, product_export, lng_export, import_terminal, refinery, sts_hub
    country = Column(String(3), index=True)
    latitude = Column(Float)
    longitude = Column(Float)
    radius_km = Column(Float, default=8.0)
    commodity = Column(String(50))  # crude, products, lng, lpg, mixed
    production_capacity_bpd = Column(Float)
    production_capacity_mtpa = Column(Float)
    operator_name = Column(String(200))
    owner_name = Column(String(200), index=True)
    owner_sanctioned = Column(Boolean, default=False, nullable=False)
    is_sanctioned_facility = Column(Boolean, default=False, nullable=False, index=True)
    sanctioning_authority = Column(String(20))
    notes = Column(String(300))
    tanker_calls_7d = Column(Integer, default=0)
    tanker_calls_30d = Column(Integer, default=0)
    estimated_utilization = Column(Float)
    last_activity_at = Column(DateTime)
    created_at = Column(DateTime, default=utcnow, nullable=False)

    __table_args__ = (Index("ix_energy_facilities_country_type", "country", "facility_type"),)


class OilTankerShipment(Base):
    """A tanker voyage reconstructed from port calls: loading at a facility, discharge at the next."""

    __tablename__ = "oil_tanker_shipments"

    id = Column(Integer, primary_key=True)
    vessel_id = Column(Integer, ForeignKey("vessels.id"), nullable=False, index=True)
    vessel_name = Column(String(200))
    mmsi = Column(String(20), index=True)
    imo = Column(String(20))
    flag = Column(String(3))
    cargo_type = Column(String(50))  # crude, products, lng, lpg, unknown
    cargo_volume_barrels = Column(Float)
    origin_country = Column(String(3), index=True)
    destination_country = Column(String(3), index=True)
    loading_facility_id = Column(Integer, ForeignKey("energy_facilities.id"), index=True)
    loading_location = Column(String(200))
    loading_date = Column(DateTime, index=True)
    loading_port_call_id = Column(Integer, ForeignKey("port_call_events.id"))
    discharge_facility_id = Column(Integer, ForeignKey("energy_facilities.id"))
    discharge_location = Column(String(200))
    discharge_date = Column(DateTime)
    discharge_port_call_id = Column(Integer, ForeignKey("port_call_events.id"))
    draught_departure = Column(Float)
    draught_arrival = Column(Float)
    laden = Column(Boolean)
    sanctioned_route = Column(Boolean, default=False, nullable=False, index=True)
    dark_oil_suspect = Column(Boolean, default=False, nullable=False, index=True)
    transshipment_suspect = Column(Boolean, default=False, nullable=False)
    status = Column(String(30), default="underway")  # loading, underway, discharged
    risk_score = Column(Float)
    evidence = Column(JSON)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    vessel = relationship("Vessel")
    loading_facility = relationship("EnergyFacility", foreign_keys=[loading_facility_id])
    discharge_facility = relationship("EnergyFacility", foreign_keys=[discharge_facility_id])

    __table_args__ = (Index("ix_oil_tanker_shipments_vessel_dates", "vessel_id", "loading_date", "discharge_date"),)


class DarkOilIndicator(Base):
    """Evidence that a tanker is moving sanctioned-origin oil."""

    __tablename__ = "dark_oil_indicators"

    id = Column(Integer, primary_key=True)
    tanker_id = Column(Integer, ForeignKey("vessels.id"), nullable=False, index=True)
    tanker_name = Column(String(200))
    mmsi = Column(String(20), index=True)
    detected_pattern = Column(String(100), index=True)  # sanctioned_loading, ais_gap_after_loading, sts_transfer, spoofed_position, sts_hub_loitering, identity_change
    suspected_origin = Column(String(3))
    suspected_destination = Column(String(3))
    evidence = Column(JSON)
    confidence_score = Column(Float, index=True)
    severity = Column(String(20))
    summary = Column(String(300))
    shipment_id = Column(Integer, ForeignKey("oil_tanker_shipments.id"))
    detected_at = Column(DateTime, default=utcnow, nullable=False, index=True)
    voyage_start = Column(DateTime)
    investigation_status = Column(String(50), default="flagged")

    tanker = relationship("Vessel")

    __table_args__ = (Index("ix_dark_oil_indicators_tanker_detected", "tanker_id", "detected_at"),)


class EnergyFlowSnapshot(Base):
    """Daily aggregate of tanker activity per facility, for trend and price correlation."""

    __tablename__ = "energy_flow_snapshots"

    id = Column(Integer, primary_key=True)
    day = Column(DateTime, nullable=False, index=True)
    facility_id = Column(Integer, ForeignKey("energy_facilities.id"), nullable=False, index=True)
    tanker_arrivals = Column(Integer, default=0)
    tanker_departures = Column(Integer, default=0)
    laden_departures = Column(Integer, default=0)
    estimated_barrels = Column(Float)
    flagged_tankers = Column(Integer, default=0)

    __table_args__ = (Index("ix_energy_flow_snapshots_day_facility", "day", "facility_id", unique=True),)
