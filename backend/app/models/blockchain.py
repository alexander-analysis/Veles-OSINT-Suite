"""Blockchain tracker tables (ecosystem bot 5)."""

from sqlalchemy import JSON, Boolean, Column, DateTime, Float, ForeignKey, Index, Integer, String
from sqlalchemy.orm import relationship

from app.models.base import Base, utcnow


class BlockchainWallet(Base):
    """A monitored address: sanctioned, labelled (exchange / mixer) or discovered through activity."""

    __tablename__ = "blockchain_wallets"

    id = Column(Integer, primary_key=True)
    blockchain = Column(String(30), nullable=False, index=True)  # bitcoin, ethereum, tron, litecoin, ...
    address = Column(String(200), nullable=False, index=True)
    wallet_type = Column(String(50), index=True)  # sanctioned, exchange, mixer, contract, individual, unknown
    label = Column(String(200))  # e.g. "Binance 14", "Tornado Cash 10 ETH"
    owner_name = Column(String(300), index=True)
    owner_entity_id = Column(Integer, ForeignKey("sanctions_entities.id"), index=True)
    is_sanctioned = Column(Boolean, default=False, nullable=False, index=True)
    sanctioning_authority = Column(String(20))
    sanctions_programs = Column(JSON)
    sanctions_confidence = Column(Float)
    risk_score = Column(Float, index=True)
    risk_factors = Column(JSON)
    balance_native = Column(Float)
    balance_usd = Column(Float)
    total_inflow_native = Column(Float)
    total_outflow_native = Column(Float)
    transaction_count = Column(Integer)
    last_active = Column(DateTime, index=True)
    last_checked = Column(DateTime, index=True)
    confidence_score = Column(Float)
    verified_owner = Column(Boolean, default=False, nullable=False)
    watch = Column(Boolean, default=True, nullable=False, index=True)  # polled by the bot
    notes = Column(String(500))
    created_at = Column(DateTime, default=utcnow, nullable=False)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    entity = relationship("SanctionsEntity")

    __table_args__ = (
        Index("ix_blockchain_wallets_chain_address", "blockchain", "address", unique=True),
        Index("ix_blockchain_wallets_owner_chain", "owner_name", "blockchain"),
    )


class BlockchainTransaction(Base):
    """An observed on-chain transfer of interest (whale, sanctioned or mixer counterparty, watched wallet)."""

    __tablename__ = "blockchain_transactions"

    id = Column(Integer, primary_key=True)
    blockchain = Column(String(30), nullable=False, index=True)
    tx_hash = Column(String(200), nullable=False, index=True)
    timestamp = Column(DateTime, nullable=False, index=True)
    block_number = Column(Integer)
    from_address = Column(String(200), index=True)
    to_address = Column(String(200), index=True)
    amount = Column(Float)
    amount_usd = Column(Float, index=True)
    token_type = Column(String(30))  # BTC, ETH, USDT, USDC, TRX
    involves_mixer = Column(Boolean, default=False, nullable=False, index=True)
    involves_sanctioned = Column(Boolean, default=False, nullable=False, index=True)
    involves_exchange = Column(Boolean, default=False, nullable=False, index=True)
    risk_score = Column(Float, index=True)
    suspicious_pattern = Column(String(100))  # whale_transfer, sanctioned_counterparty, mixer_usage, exchange_cashout
    source_entity = Column(String(300))
    destination_entity = Column(String(300))
    chain_length = Column(Integer)
    details = Column(JSON)
    detected_at = Column(DateTime, default=utcnow, nullable=False)
    acknowledged = Column(Boolean, default=False, nullable=False)

    __table_args__ = (
        Index("ix_blockchain_transactions_chain_hash", "blockchain", "tx_hash", unique=True),
        Index("ix_blockchain_transactions_from_to_time", "from_address", "to_address", "timestamp"),
    )


class WalletCluster(Base):
    """Addresses believed to share an owner (co-spend heuristic on Bitcoin inputs, labels)."""

    __tablename__ = "wallet_clusters"

    id = Column(Integer, primary_key=True)
    cluster_id = Column(String(64), unique=True, nullable=False)
    blockchain = Column(String(30), nullable=False)
    estimated_owner = Column(String(300))
    wallet_count = Column(Integer)
    linked_addresses = Column(JSON)
    total_holdings_usd = Column(Float)
    risk_score = Column(Float)
    includes_sanctioned = Column(Boolean, default=False, nullable=False)
    evidence = Column(JSON)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)
