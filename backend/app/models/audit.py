"""Audit & compliance tables.

``AuditLog`` is append-only.  Immutability is enforced twice:

1. ORM level - ``before_update`` / ``before_delete`` listeners raise
   ``ImmutableRecordError`` for any mapped ``AuditLog`` instance.
2. Database level - SQLite triggers (installed by migration ``001``) abort any
   ``UPDATE`` or ``DELETE`` on ``audit_logs``, which also covers bulk queries
   and anything that bypasses the ORM.
"""

from sqlalchemy import JSON, Boolean, Column, DateTime, ForeignKey, Index, Integer, String, event
from sqlalchemy.orm import relationship

from app.models.base import Base, utcnow


class ImmutableRecordError(RuntimeError):
    """Raised when code tries to modify or delete an audit-log row."""


class AuditLog(Base):
    """Immutable transaction log of all system and operator actions."""

    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, nullable=False, index=True, default=utcnow)
    action_type = Column(String(50), nullable=False, index=True)  # breach_detected, investigation_started, cleared, escalated, export, config_updated
    user_id = Column(String(100))  # username if multi-user, else "system"
    vessel_id = Column(Integer, ForeignKey("vessels.id"))
    breach_id = Column(Integer, ForeignKey("sanctions_breaches.id"))
    sanctioned_entity_name = Column(String(200))
    sanctioning_authorities = Column(JSON)  # which authorities were involved
    rationale = Column(String(1000))  # why this action was taken
    supporting_data = Column(JSON)  # evidence: coordinates, anomalies, ...
    related_entities = Column(JSON)  # linked vessels, owners, ...
    classification_level = Column(String(50), default="UNCLASSIFIED")  # UNCLASSIFIED, CONFIDENTIAL, SECRET
    source_systems = Column(JSON)  # which bots / integrations were involved

    # Immutability marker (informational - enforcement is via listeners + triggers)
    is_final = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    created_by = Column(String(100))

    breach = relationship("SanctionsBreach", back_populates="audit_entries")

    __table_args__ = (
        Index("ix_audit_logs_timestamp_action", "timestamp", "action_type"),
        Index("ix_audit_logs_vessel_timestamp", "vessel_id", "timestamp"),
        Index("ix_audit_logs_user_timestamp", "user_id", "timestamp"),
    )


@event.listens_for(AuditLog, "before_update")
def _forbid_audit_update(_mapper, _connection, target: AuditLog) -> None:
    raise ImmutableRecordError(f"audit_logs row {target.id} is immutable and cannot be updated")


@event.listens_for(AuditLog, "before_delete")
def _forbid_audit_delete(_mapper, _connection, target: AuditLog) -> None:
    raise ImmutableRecordError(f"audit_logs row {target.id} is immutable and cannot be deleted")


class DataRetentionPolicy(Base):
    """Configurable data retention settings, one row per data type."""

    __tablename__ = "data_retention_policies"

    id = Column(Integer, primary_key=True)
    data_type = Column(String(50), nullable=False, unique=True)  # market_candles, vessel_positions, ...
    retention_days = Column(Integer, nullable=False)
    compression_after_days = Column(Integer)  # when to thin to lower granularity
    last_purge_at = Column(DateTime)
    records_purged = Column(Integer)  # rows removed by the last purge
    enabled = Column(Boolean, default=True, nullable=False)
