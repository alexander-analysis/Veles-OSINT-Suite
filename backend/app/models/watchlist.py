"""Analyst watchlists: things to be told about, and every time one of them surfaced."""

from sqlalchemy import JSON, Boolean, Column, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import relationship

from app.models.base import Base
from app.utils.time import utcnow


class WatchlistItem(Base):
    """A vessel, listed party, company, wallet, aircraft, domain or free keyword an analyst wants to follow."""

    __tablename__ = "watchlist_items"

    id = Column(Integer, primary_key=True)
    kind = Column(String(20), nullable=False, index=True)  # vessel, entity, company, wallet, aircraft, domain, keyword
    key = Column(String(300), nullable=False)  # MMSI, sanctions entity id, LEI or company name, address, registration, domain, text
    label = Column(String(300))
    note = Column(String(500))
    created_by = Column(String(100), default="analyst")
    created_at = Column(DateTime, default=utcnow, nullable=False)
    active = Column(Boolean, default=True, nullable=False, index=True)
    alert = Column(Boolean, default=True, nullable=False)  # send an instant notification on a hit
    last_checked_at = Column(DateTime)
    last_hit_at = Column(DateTime, index=True)
    hit_count = Column(Integer, default=0, nullable=False)

    hits = relationship("WatchlistHit", back_populates="item", cascade="all, delete-orphan")

    __table_args__ = (Index("ix_watchlist_items_kind_key", "kind", "key", unique=True),)


class WatchlistHit(Base):
    """One record that touched a watched item."""

    __tablename__ = "watchlist_hits"

    id = Column(Integer, primary_key=True)
    item_id = Column(Integer, ForeignKey("watchlist_items.id"), nullable=False, index=True)
    record_type = Column(String(40), nullable=False)  # evasion_event, sanctions_breach, port_call, transshipment, psc_event, shipment, dark_oil, legal_event, transfer, sighting, breach_event, geopolitical_event, narrative, infra_asset
    record_id = Column(Integer, nullable=False)
    timestamp = Column(DateTime, nullable=False, index=True)
    severity = Column(String(20))
    summary = Column(String(300))
    href = Column(String(200))
    details = Column(JSON)
    created_at = Column(DateTime, default=utcnow, nullable=False)

    item = relationship("WatchlistItem", back_populates="hits")

    __table_args__ = (Index("ix_watchlist_hits_item_record", "item_id", "record_type", "record_id", unique=True),)
