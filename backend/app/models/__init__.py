"""ORM models.

Importing this package registers every table on ``Base.metadata`` so Alembic
autogenerate and cross-module relationships (string references) resolve.
"""

from app.models.audit import AuditLog, DataRetentionPolicy
from app.models.blockchain import BlockchainTransaction, BlockchainWallet, WalletCluster
from app.models.corporate import Company, CompanyDirector, OwnershipChain, Shareholder
from app.models.correlation import CompositeAlert, SignalCorrelation
from app.models.energy import DarkOilIndicator, EnergyFacility, EnergyFlowSnapshot, OilTankerShipment
from app.models.geopolitical import EventCorrelation, GeopoliticalEvent, NewsSource
from app.models.base import Base
from app.models.maritime import (
    EvasionEvent,
    PortCallEvent,
    SanctionsBreach,
    ShippingLaneViolation,
    TransshipmentEvent,
    Vessel,
    VesselPosition,
)
from app.models.market import CoordinationEvent, LiquidationCascade, MarketAlert, MarketCandle
from app.models.sanctions import SanctionsEntity, SanctionsProgramTracking, SanctionsUpdate

__all__ = [
    "Base",
    "AuditLog",
    "DataRetentionPolicy",
    "PortCallEvent",
    "SanctionsBreach",
    "ShippingLaneViolation",
    "TransshipmentEvent",
    "Vessel",
    "VesselPosition",
    "CoordinationEvent",
    "LiquidationCascade",
    "MarketAlert",
    "MarketCandle",
    "SanctionsEntity",
    "SanctionsProgramTracking",
    "SanctionsUpdate",
    "EvasionEvent",
    "BlockchainTransaction", "BlockchainWallet", "WalletCluster",
    "Company", "CompanyDirector", "OwnershipChain", "Shareholder",
    "CompositeAlert", "SignalCorrelation",
    "DarkOilIndicator", "EnergyFacility", "EnergyFlowSnapshot", "OilTankerShipment",
    "EventCorrelation", "GeopoliticalEvent", "NewsSource",
]
