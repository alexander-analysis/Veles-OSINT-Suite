"""/api/blockchain/* - sanctioned wallets, flagged transfers, whale feed, clusters."""

from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.analysis.blockchain import cluster_id, normalize_address
from app.bots.blockchain import blockchain_bot
from app.bots.runtime import bot_loop
from app.database import get_db
from app.models.audit import AuditLog
from app.models.blockchain import BlockchainTransaction, BlockchainWallet, WalletCluster
from app.schemas.blockchain import AddWalletRequest, ClusterOut, TransactionOut, TransactionsResponse, WalletDetail, WalletOut, WalletsResponse
from app.utils.serialization import jsonable
from app.utils.time import utcnow

router = APIRouter(tags=["blockchain"])

EXPLORERS = {
    "bitcoin": "https://mempool.space/address/{address}",
    "ethereum": "https://etherscan.io/address/{address}",
    "tron": "https://tronscan.org/#/address/{address}",
}


@router.get("/wallets", response_model=WalletsResponse)
def list_wallets(
    chain: str | None = Query(None, description="bitcoin, ethereum, tron, ..."),
    wallet_type: str | None = Query(None, description="sanctioned, exchange, mixer, individual, delisted"),
    sanctioned: bool | None = None,
    active_hours: int | None = Query(None, ge=1, description="Only wallets active in the last N hours"),
    q: str | None = Query(None, max_length=120, description="Address / owner / label substring"),
    min_balance_usd: float | None = Query(None, ge=0),
    sort: str = Query("balance", pattern="^(balance|last_active|risk|owner)$"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> WalletsResponse:
    query = select(BlockchainWallet)
    if chain:
        query = query.where(BlockchainWallet.blockchain == chain)
    if wallet_type:
        query = query.where(BlockchainWallet.wallet_type == wallet_type)
    if sanctioned is not None:
        query = query.where(BlockchainWallet.is_sanctioned.is_(sanctioned))
    if active_hours:
        query = query.where(BlockchainWallet.last_active >= utcnow() - timedelta(hours=active_hours))
    if min_balance_usd is not None:
        query = query.where(BlockchainWallet.balance_usd >= min_balance_usd)
    if q:
        pattern = f"%{q}%"
        query = query.where(or_(BlockchainWallet.address.ilike(pattern), BlockchainWallet.owner_name.ilike(pattern), BlockchainWallet.label.ilike(pattern)))
    total = db.execute(select(func.count()).select_from(query.subquery())).scalar() or 0
    order = {
        "balance": BlockchainWallet.balance_usd.desc().nulls_last(),
        "last_active": BlockchainWallet.last_active.desc().nulls_last(),
        "risk": BlockchainWallet.risk_score.desc().nulls_last(),
        "owner": BlockchainWallet.owner_name.asc(),
    }[sort]
    rows = db.execute(query.order_by(order, BlockchainWallet.id).limit(limit).offset(offset)).scalars().all()
    return WalletsResponse(total=total, limit=limit, offset=offset, filters={"chain": chain, "wallet_type": wallet_type, "sanctioned": sanctioned, "q": q, "sort": sort}, wallets=[WalletOut.model_validate(r) for r in rows])


@router.get("/wallets/{chain}/{address}", response_model=WalletDetail)
def wallet_detail(chain: str, address: str, db: Session = Depends(get_db)) -> WalletDetail:
    address = normalize_address(chain, address)
    wallet = db.execute(select(BlockchainWallet).where(BlockchainWallet.blockchain == chain, BlockchainWallet.address == address)).scalar_one_or_none()
    if wallet is None:
        raise HTTPException(status_code=404, detail="Wallet not tracked")
    txs = db.execute(
        select(BlockchainTransaction)
        .where(BlockchainTransaction.blockchain == chain, or_(BlockchainTransaction.from_address == address, BlockchainTransaction.to_address == address))
        .order_by(BlockchainTransaction.timestamp.desc())
        .limit(100)
    ).scalars().all()
    cluster = db.execute(select(WalletCluster).where(WalletCluster.cluster_id == cluster_id(chain, address))).scalar_one_or_none()
    explorer = EXPLORERS.get(chain)
    return WalletDetail(
        wallet=WalletOut.model_validate(wallet),
        transactions=[TransactionOut.model_validate(t) for t in txs],
        cluster=ClusterOut.model_validate(cluster) if cluster else None,
        explorer_url=explorer.format(address=address) if explorer else None,
    )


@router.post("/wallets", response_model=WalletOut, status_code=201)
def add_wallet(body: AddWalletRequest, db: Session = Depends(get_db)) -> WalletOut:
    """Track an analyst-supplied address (audited)."""
    address = normalize_address(body.blockchain, body.address.strip())
    existing = db.execute(select(BlockchainWallet).where(BlockchainWallet.blockchain == body.blockchain, BlockchainWallet.address == address)).scalar_one_or_none()
    if existing:
        existing.watch = body.watch
        existing.notes = body.notes or existing.notes
        if body.label:
            existing.label = body.label
        wallet = existing
    else:
        wallet = BlockchainWallet(blockchain=body.blockchain, address=address, wallet_type=body.wallet_type, label=body.label, owner_name=body.owner_name, watch=body.watch, notes=body.notes,
                                  confidence_score=0.5, risk_score=0.8 if body.wallet_type == "mixer" else 0.3, risk_factors=["analyst_added"])
        db.add(wallet)
    db.add(AuditLog(action_type="wallet_watch_added", user_id=body.analyst or "analyst", rationale=body.notes or f"Watch {body.blockchain} {address}", supporting_data={"blockchain": body.blockchain, "address": address, "label": body.label},
                    source_systems=["api.blockchain"], created_by=body.analyst or "analyst"))
    db.commit()
    db.refresh(wallet)
    blockchain_bot.labels.pop((body.blockchain, address), None)
    if wallet.wallet_type in ("exchange", "mixer"):
        blockchain_bot.labels[(body.blockchain, address)] = {"id": wallet.id, "wallet_type": wallet.wallet_type, "owner_name": wallet.owner_name, "label": wallet.label, "is_sanctioned": False}
    return WalletOut.model_validate(wallet)


@router.get("/transactions", response_model=TransactionsResponse)
def list_transactions(
    hours: int = Query(24, ge=1, le=24 * 90),
    chain: str | None = None,
    pattern: str | None = Query(None, description="whale_transfer, sanctioned_counterparty, exchange_cashout, mixer_usage, ..."),
    involves_sanctioned: bool | None = None,
    involves_mixer: bool | None = None,
    min_usd: float | None = Query(None, ge=0),
    address: str | None = Query(None, max_length=120),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
) -> TransactionsResponse:
    since = utcnow() - timedelta(hours=hours)
    query = select(BlockchainTransaction).where(BlockchainTransaction.timestamp >= since)
    if chain:
        query = query.where(BlockchainTransaction.blockchain == chain)
    if pattern:
        query = query.where(BlockchainTransaction.suspicious_pattern == pattern)
    if involves_sanctioned is not None:
        query = query.where(BlockchainTransaction.involves_sanctioned.is_(involves_sanctioned))
    if involves_mixer is not None:
        query = query.where(BlockchainTransaction.involves_mixer.is_(involves_mixer))
    if min_usd is not None:
        query = query.where(BlockchainTransaction.amount_usd >= min_usd)
    if address:
        query = query.where(or_(BlockchainTransaction.from_address == address, BlockchainTransaction.to_address == address, BlockchainTransaction.from_address == address.lower(), BlockchainTransaction.to_address == address.lower()))
    total = db.execute(select(func.count()).select_from(query.subquery())).scalar() or 0
    rows = db.execute(query.order_by(BlockchainTransaction.timestamp.desc(), BlockchainTransaction.id.desc()).limit(limit)).scalars().all()
    return TransactionsResponse(total=total, limit=limit, filters={"hours": hours, "chain": chain, "pattern": pattern, "involves_sanctioned": involves_sanctioned, "min_usd": min_usd}, transactions=[TransactionOut.model_validate(r) for r in rows])


@router.get("/whales", response_model=TransactionsResponse)
def list_whales(hours: int = Query(24, ge=1, le=24 * 30), limit: int = Query(50, ge=1, le=500), db: Session = Depends(get_db)) -> TransactionsResponse:
    since = utcnow() - timedelta(hours=hours)
    query = select(BlockchainTransaction).where(BlockchainTransaction.timestamp >= since, BlockchainTransaction.suspicious_pattern == "whale_transfer")
    total = db.execute(select(func.count()).select_from(query.subquery())).scalar() or 0
    rows = db.execute(query.order_by(BlockchainTransaction.amount_usd.desc().nulls_last()).limit(limit)).scalars().all()
    return TransactionsResponse(total=total, limit=limit, filters={"hours": hours, "pattern": "whale_transfer"}, transactions=[TransactionOut.model_validate(r) for r in rows])


@router.post("/transactions/{tx_id}/acknowledge", response_model=TransactionOut)
def acknowledge(tx_id: int, analyst: str | None = Query(None, max_length=100), db: Session = Depends(get_db)) -> TransactionOut:
    row = db.get(BlockchainTransaction, tx_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Transaction not found")
    row.acknowledged = True
    db.add(AuditLog(action_type="alert_acknowledged", user_id=analyst or "analyst", rationale=f"Blockchain transfer {row.blockchain} {row.tx_hash[:20]} acknowledged", supporting_data={"tx_id": tx_id, "pattern": row.suspicious_pattern},
                    source_systems=["api.blockchain"], created_by=analyst or "analyst"))
    db.commit()
    db.refresh(row)
    return TransactionOut.model_validate(row)


@router.get("/clusters", response_model=list[ClusterOut])
def list_clusters(limit: int = Query(100, ge=1, le=500), db: Session = Depends(get_db)) -> list[ClusterOut]:
    rows = db.execute(select(WalletCluster).order_by(WalletCluster.includes_sanctioned.desc(), WalletCluster.wallet_count.desc()).limit(limit)).scalars().all()
    return [ClusterOut.model_validate(r) for r in rows]


@router.get("/summary")
def summary(hours: int = Query(24, ge=1, le=24 * 30), db: Session = Depends(get_db)) -> dict[str, Any]:
    return jsonable(blockchain_bot.summary(db, hours))


@router.get("/status")
def get_status() -> dict[str, Any]:
    return jsonable(blockchain_bot.status())


@router.post("/refresh", status_code=202)
def trigger_refresh(job: str = Query("all", pattern="^(all|sync|prices|poll|scan)$")) -> dict[str, Any]:
    jobs = {"sync": blockchain_bot.sync_sanctioned_wallets, "prices": blockchain_bot.refresh_prices, "poll": blockchain_bot.poll_wallets, "scan": blockchain_bot.scan_ethereum}
    selected = list(jobs) if job == "all" else [job]
    for name in selected:
        bot_loop.submit(jobs[name]())
    return {"status": "started", "jobs": selected}
