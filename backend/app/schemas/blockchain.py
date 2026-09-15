"""Blockchain tracker API schemas."""

from datetime import datetime
from typing import Any

from pydantic import Field

from app.schemas.common import APIModel


class WalletOut(APIModel):
    id: int
    blockchain: str
    address: str
    wallet_type: str | None = None
    label: str | None = None
    owner_name: str | None = None
    owner_entity_id: int | None = None
    is_sanctioned: bool = False
    sanctioning_authority: str | None = None
    sanctions_programs: list[str] | None = None
    risk_score: float | None = None
    risk_factors: list[str] | None = None
    balance_native: float | None = None
    balance_usd: float | None = None
    total_inflow_native: float | None = None
    total_outflow_native: float | None = None
    transaction_count: int | None = None
    last_active: datetime | None = None
    last_checked: datetime | None = None
    confidence_score: float | None = None
    verified_owner: bool = False
    watch: bool = True
    notes: str | None = None
    created_at: datetime


class WalletsResponse(APIModel):
    total: int
    limit: int
    offset: int
    filters: dict[str, Any]
    wallets: list[WalletOut]


class TransactionOut(APIModel):
    id: int
    blockchain: str
    tx_hash: str
    timestamp: datetime
    block_number: int | None = None
    from_address: str | None = None
    to_address: str | None = None
    amount: float | None = None
    amount_usd: float | None = None
    token_type: str | None = None
    involves_mixer: bool = False
    involves_sanctioned: bool = False
    involves_exchange: bool = False
    risk_score: float | None = None
    suspicious_pattern: str | None = None
    source_entity: str | None = None
    destination_entity: str | None = None
    details: dict[str, Any] | None = None
    detected_at: datetime
    acknowledged: bool = False


class TransactionsResponse(APIModel):
    total: int
    limit: int
    filters: dict[str, Any]
    transactions: list[TransactionOut]


class ClusterOut(APIModel):
    id: int
    cluster_id: str
    blockchain: str
    estimated_owner: str | None = None
    wallet_count: int | None = None
    linked_addresses: list[str] | None = None
    total_holdings_usd: float | None = None
    risk_score: float | None = None
    includes_sanctioned: bool = False
    evidence: dict[str, Any] | None = None
    updated_at: datetime


class WalletDetail(APIModel):
    wallet: WalletOut
    transactions: list[TransactionOut]
    cluster: ClusterOut | None = None
    explorer_url: str | None = None


class AddWalletRequest(APIModel):
    blockchain: str = Field(pattern="^(bitcoin|ethereum|tron)$")
    address: str = Field(min_length=20, max_length=120)
    label: str | None = Field(None, max_length=200)
    wallet_type: str = Field("individual", pattern="^(exchange|mixer|individual|contract|unknown)$")
    owner_name: str | None = Field(None, max_length=300)
    watch: bool = True
    notes: str | None = Field(None, max_length=500)
    analyst: str | None = Field(None, max_length=100)
