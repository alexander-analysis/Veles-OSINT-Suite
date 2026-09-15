"""Tron account / transfer lookups through the public Tronscan API (keyless, throttled)."""

import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import httpx

from app.data.crypto_labels import TRON_USDT
from app.utils.logger import logger
from app.utils.time import from_unix_seconds

log = logger.bind(component="tronscan")

BASE = "https://apilist.tronscanapi.com/api"
UA = {"User-Agent": "VELES-OSINT/1.0 (sanctions research)"}
SUN = 1_000_000
MIN_INTERVAL = 1.2  # seconds between calls (public tier)
_last_call = 0.0
_lock = asyncio.Lock()


@dataclass
class TronAccount:
    address: str
    balance_trx: float
    usdt_balance: float
    transaction_count: int
    tokens: dict[str, float] = field(default_factory=dict)


@dataclass
class TronTransfer:
    tx_hash: str
    timestamp: datetime | None
    block: int | None
    from_address: str
    to_address: str
    amount: float
    token: str  # TRX or USDT (TRC-20)


async def _get(path: str, params: dict[str, Any]) -> Any:
    global _last_call
    async with _lock:
        wait = MIN_INTERVAL - (time.monotonic() - _last_call)
        if wait > 0:
            await asyncio.sleep(wait)
        async with httpx.AsyncClient(timeout=30, headers=UA) as client:
            response = await client.get(f"{BASE}/{path}", params=params)
        _last_call = time.monotonic()
    response.raise_for_status()
    return response.json()


async def account(address: str) -> TronAccount:
    data = await _get("account", {"address": address})
    tokens: dict[str, float] = {}
    usdt = 0.0
    for token in data.get("trc20token_balances", []) or []:
        try:
            amount = int(token.get("balance") or 0) / 10 ** int(token.get("tokenDecimal") or 6)
        except (TypeError, ValueError):
            continue
        symbol = token.get("tokenAbbr") or token.get("tokenId", "?")
        tokens[symbol] = tokens.get(symbol, 0.0) + amount
        if token.get("tokenId") == TRON_USDT:
            usdt += amount
    return TronAccount(
        address=address,
        balance_trx=(data.get("balance") or 0) / SUN,
        usdt_balance=usdt,
        transaction_count=int(data.get("transactions") or data.get("totalTransactionCount") or 0),
        tokens=tokens,
    )


async def trc20_transfers(address: str, limit: int = 20) -> list[TronTransfer]:
    """Newest TRC-20 transfers (USDT is what matters for sanctions flows)."""
    data = await _get("token_trc20/transfers", {"relatedAddress": address, "limit": limit, "start": 0})
    out = []
    for row in data.get("token_transfers", []) or []:
        info = row.get("tokenInfo") or {}
        decimals = int(info.get("tokenDecimal") or 6)
        symbol = info.get("tokenAbbr") or "TRC20"
        if row.get("contract_address") == TRON_USDT:
            symbol = "USDT"
        try:
            amount = int(row.get("quant") or 0) / 10**decimals
        except (TypeError, ValueError):
            continue
        out.append(
            TronTransfer(
                tx_hash=row.get("transaction_id", ""),
                timestamp=from_unix_seconds(row["block_ts"] / 1000) if row.get("block_ts") else None,
                block=row.get("block"),
                from_address=row.get("from_address", ""),
                to_address=row.get("to_address", ""),
                amount=amount,
                token=symbol,
            )
        )
    return out


async def trx_transfers(address: str, limit: int = 20) -> list[TronTransfer]:
    data = await _get("transaction", {"address": address, "limit": limit, "start": 0, "sort": "-timestamp"})
    out = []
    for row in data.get("data", []) or []:
        if row.get("contractType") != 1:  # TransferContract only (native TRX)
            continue
        raw = row.get("contractData") or {}
        try:
            amount = int(raw.get("amount") or 0) / SUN
        except (TypeError, ValueError):
            continue
        out.append(
            TronTransfer(
                tx_hash=row.get("hash", ""),
                timestamp=from_unix_seconds(row["timestamp"] / 1000) if row.get("timestamp") else None,
                block=row.get("block"),
                from_address=row.get("ownerAddress", ""),
                to_address=row.get("toAddress", ""),
                amount=amount,
                token="TRX",
            )
        )
    return out
