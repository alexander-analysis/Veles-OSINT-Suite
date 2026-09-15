"""Blockchain tracker (ecosystem bot 5) - follows the money behind the sanctions lists.

* ``sync_sanctioned_wallets`` - every OFAC "Digital Currency Address" becomes a
  watched ``BlockchainWallet`` (plus curated exchange / mixer labels).
* ``poll_wallets`` - Bitcoin (Blockstream), Ethereum (public RPC, batched) and
  Tron (Tronscan) balances / activity for the watched set; new transfers are
  scored and stored, Bitcoin co-spends grow ``WalletCluster`` rows.
* ``scan_ethereum`` - every new block: native ETH whales and every USDT/USDC/DAI
  transfer that is large or touches a sanctioned / mixer address.
* Bitcoin unconfirmed stream - real-time whale and sanctioned-address hits.

Everything is keyless; an ``ETHEREUM_RPC_URL`` in .env swaps the RPC endpoint.
"""

import asyncio
from collections import Counter
from datetime import datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.analysis.blockchain import TRACEABLE, TxAssessment, assess_transaction, cluster_id, cospend_cluster, normalize_address, parse_ofac_addresses, usd_value
from app.data.crypto_labels import LABELS
from app.database import SessionLocal
from app.integrations import blockstream, tronscan
from app.integrations.ethereum_rpc import EthereumRPC, EthTransfer, topic_for
from app.models.audit import AuditLog
from app.models.blockchain import BlockchainTransaction, BlockchainWallet, WalletCluster
from app.models.market import MarketCandle
from app.models.sanctions import SanctionsEntity
from app.utils import config_store
from app.utils.logger import logger
from app.utils.time import from_unix_seconds, utcnow

log = logger.bind(component="blockchain")

TOKEN_BY_CHAIN = {"bitcoin": "BTC", "ethereum": "ETH", "tron": "TRX"}


def _config() -> dict[str, Any]:
    return config_store.get_config().get("blockchain", {})


class BlockchainBot:
    def __init__(self) -> None:
        self.eth = EthereumRPC()
        self.stream: blockstream.BitcoinMempoolStream | None = None
        self.prices: dict[str, float] = {"USDT": 1.0, "USDC": 1.0, "DAI": 1.0}
        self.last_run: dict[str, datetime] = {}
        self.last_result: dict[str, Any] = {}
        self.labels: dict[tuple[str, str], dict[str, Any]] = {}  # (chain, address) -> {wallet_type, owner_name, label, id}
        self._eth_last_block: int | None = None
        self._stream_buffer: list[dict[str, Any]] = []
        self._stream_hits = 0
        self._whale_btc = 100.0  # cached from settings; the stream callback runs several times a second

    # ------------------------------------------------------------- status
    def status(self) -> dict[str, Any]:
        return {
            "last_run": dict(self.last_run),
            "last_result": self.last_result,
            "prices": self.prices,
            "labels_loaded": len(self.labels),
            "eth_last_block": self._eth_last_block,
            "rpc_calls": self.eth.calls,
            "btc_stream": self.stream.status() if self.stream else {"connected": False},
            "stream_hits": self._stream_hits,
        }

    # ----------------------------------------------------------- labels
    def _load_labels(self, db: Session) -> None:
        rows = db.execute(select(BlockchainWallet.id, BlockchainWallet.blockchain, BlockchainWallet.address, BlockchainWallet.wallet_type, BlockchainWallet.owner_name, BlockchainWallet.label, BlockchainWallet.is_sanctioned)
                          .where(BlockchainWallet.wallet_type.in_(["sanctioned", "exchange", "mixer"]))).all()
        self.labels = {(r.blockchain, r.address): {"id": r.id, "wallet_type": r.wallet_type, "owner_name": r.owner_name, "label": r.label, "is_sanctioned": r.is_sanctioned} for r in rows}

    def label_for(self, blockchain: str, address: str | None) -> list[dict[str, Any]]:
        if not address:
            return []
        entry = self.labels.get((blockchain, normalize_address(blockchain, address)))
        return [entry] if entry else []

    # ---------------------------------------------------------- sync job
    async def sync_sanctioned_wallets(self) -> dict[str, Any]:
        result = await asyncio.to_thread(self._sync)
        self.last_run["sync"] = utcnow()
        self.last_result["sync"] = result
        log.info("wallet sync: {}", result)
        return result

    def _sync(self) -> dict[str, Any]:
        with SessionLocal() as db:
            existing = {(w.blockchain, w.address): w for w in db.execute(select(BlockchainWallet)).scalars()}
            now = utcnow()
            added = updated = 0
            seen: set[tuple[str, str]] = set()
            entities = db.execute(select(SanctionsEntity).where(SanctionsEntity.remarks.like("%Digital Currency Address%"))).scalars().all()
            for entity in entities:
                for item in parse_ofac_addresses(entity.remarks):
                    key = (item.blockchain, item.address)
                    seen.add(key)
                    wallet = existing.get(key)
                    if wallet is None:
                        wallet = BlockchainWallet(blockchain=item.blockchain, address=item.address, watch=item.blockchain in TRACEABLE, confidence_score=1.0, verified_owner=True)
                        db.add(wallet)
                        existing[key] = wallet
                        added += 1
                    elif wallet.owner_entity_id != entity.id or wallet.is_sanctioned != bool(entity.is_active):
                        updated += 1
                    wallet.wallet_type = "sanctioned" if entity.is_active else "delisted"
                    wallet.is_sanctioned = bool(entity.is_active)
                    wallet.label = f"OFAC {item.symbol} - {entity.name[:150]}"
                    wallet.owner_name = entity.name[:300]
                    wallet.owner_entity_id = entity.id
                    wallet.sanctioning_authority = entity.designating_authority
                    wallet.sanctions_programs = entity.programs
                    wallet.sanctions_confidence = 1.0
                    wallet.risk_score = 1.0 if entity.is_active else 0.6
                    wallet.risk_factors = ["ofac_listed", *(entity.programs or [])[:5]]
            for chain, address, label, wallet_type, owner, confidence in LABELS:
                key = (chain, normalize_address(chain, address))
                if key in seen or key in existing:
                    continue
                db.add(BlockchainWallet(blockchain=chain, address=key[1], wallet_type=wallet_type, label=label, owner_name=owner, confidence_score=confidence,
                                        risk_score=0.8 if wallet_type == "mixer" else 0.2, risk_factors=[wallet_type], watch=False, verified_owner=False, last_checked=None))
                existing[key] = None
                added += 1
            db.commit()
            self._load_labels(db)
            counts = dict(db.execute(select(BlockchainWallet.blockchain, func.count()).where(BlockchainWallet.is_sanctioned.is_(True)).group_by(BlockchainWallet.blockchain)).all())
            if added or updated:
                db.add(AuditLog(action_type="wallets_synced", user_id="system", rationale=f"{added} wallet(s) added, {updated} updated from the sanctions lists", supporting_data=counts, source_systems=["bots.blockchain"], created_by="system"))
                db.commit()
            return {"added": added, "updated": updated, "sanctioned_by_chain": counts, "checked_at": now}

    # --------------------------------------------------------------- prices
    async def refresh_prices(self) -> dict[str, float]:
        def _from_candles() -> dict[str, float]:
            with SessionLocal() as db:
                out = {}
                for asset in ("BTC", "ETH"):
                    close = db.execute(select(MarketCandle.close).where(MarketCandle.asset == asset).order_by(MarketCandle.timestamp.desc()).limit(1)).scalar()
                    if close:
                        out[asset] = float(close)
                return out

        self.prices.update(await asyncio.to_thread(_from_candles))
        if "BTC" not in self.prices:
            btc = await blockstream.btc_usd()
            if btc:
                self.prices["BTC"] = btc
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.get("https://api.coingecko.com/api/v3/simple/price", params={"ids": "tron,ethereum", "vs_currencies": "usd"})
                if response.status_code == 200:
                    data = response.json()
                    if data.get("tron", {}).get("usd"):
                        self.prices["TRX"] = float(data["tron"]["usd"])
                    if "ETH" not in self.prices and data.get("ethereum", {}).get("usd"):
                        self.prices["ETH"] = float(data["ethereum"]["usd"])
        except Exception as exc:  # noqa: BLE001
            log.debug("coingecko unavailable: {}", exc)
        self.last_run["prices"] = utcnow()
        return self.prices

    # --------------------------------------------------------- transactions
    def _record(self, db: Session, blockchain: str, tx_hash: str, timestamp: datetime | None, block: int | None, from_address: str | None, to_address: str | None,
                amount: float | None, token: str, whale_usd: float, details: dict[str, Any] | None = None, force: bool = False) -> BlockchainTransaction | None:
        """Score and store one transfer if it is interesting (sanctioned / mixer / whale / watched)."""
        amount_usd = usd_value(amount, token, self.prices)
        assessment = assess_transaction(amount_usd, self.label_for(blockchain, from_address), self.label_for(blockchain, to_address), whale_usd, token)
        interesting = force or assessment.involves_sanctioned or assessment.involves_mixer or assessment.pattern == "whale_transfer"
        if not interesting:
            return None
        exists = db.execute(select(BlockchainTransaction.id).where(BlockchainTransaction.blockchain == blockchain, BlockchainTransaction.tx_hash == tx_hash)).scalar()
        if exists:
            return None
        row = BlockchainTransaction(
            blockchain=blockchain,
            tx_hash=tx_hash,
            timestamp=timestamp or utcnow(),
            block_number=block,
            from_address=from_address,
            to_address=to_address,
            amount=amount,
            amount_usd=amount_usd,
            token_type=token,
            involves_mixer=assessment.involves_mixer,
            involves_sanctioned=assessment.involves_sanctioned,
            involves_exchange=assessment.involves_exchange,
            risk_score=assessment.risk_score,
            suspicious_pattern=assessment.pattern,
            source_entity=assessment.source_entity,
            destination_entity=assessment.destination_entity,
            details=details or {},
        )
        db.add(row)
        self._notify(row, assessment)
        return row

    @staticmethod
    def _notify(row: BlockchainTransaction, assessment: TxAssessment) -> None:
        try:
            from app.api.stream import manager

            manager.publish("blockchain_tx", {"blockchain": row.blockchain, "tx_hash": row.tx_hash, "pattern": row.suspicious_pattern, "amount_usd": row.amount_usd, "token": row.token_type, "summary": assessment.summary})
        except Exception:  # noqa: BLE001
            pass
        if assessment.involves_sanctioned:
            from app import notifications

            notifications.send_alert("blockchain", f"Sanctioned wallet activity on {row.blockchain}", assessment.summary, severity="critical", data={"tx": row.tx_hash, "usd": row.amount_usd})

    # ------------------------------------------------------------- polling
    async def poll_wallets(self) -> dict[str, Any]:
        cfg = _config()
        if not cfg.get("enabled", True):
            return {"skipped": "disabled"}
        if not self.labels:
            await asyncio.to_thread(self._load_labels_standalone)
        whale_usd = float(cfg.get("whale_min_usd", 5_000_000))
        batch_btc, batch_trx = int(cfg.get("poll_batch_bitcoin", 12)), int(cfg.get("poll_batch_tron", 6))
        due = await asyncio.to_thread(self._due_wallets, batch_btc, batch_trx)
        result: dict[str, Any] = {"bitcoin": 0, "ethereum": 0, "tron": 0, "new_transactions": 0, "errors": 0}
        # Ethereum: one batched RPC call for the whole watched set
        eth_wallets = due.get("ethereum", [])
        if eth_wallets:
            try:
                balances = await self.eth.balances([w["address"] for w in eth_wallets])
                result["ethereum"] = len(balances)
                await asyncio.to_thread(self._apply_eth_balances, eth_wallets, balances)
            except Exception as exc:  # noqa: BLE001
                result["errors"] += 1
                log.warning("ethereum balance poll failed: {}", exc)
        for wallet in due.get("bitcoin", []):
            try:
                stats = await blockstream.address_stats(wallet["address"])
                changed = stats.tx_count != (wallet["transaction_count"] or 0) or wallet["last_checked"] is None
                transfers = await blockstream.address_transactions(wallet["address"]) if changed else []
                result["new_transactions"] += await asyncio.to_thread(self._apply_btc, wallet, stats, transfers, whale_usd)
                result["bitcoin"] += 1
            except Exception as exc:  # noqa: BLE001
                result["errors"] += 1
                if getattr(getattr(exc, "response", None), "status_code", None) == 400:
                    # the listing carries a malformed address (OFAC typos happen) - stop asking for it every cycle
                    await asyncio.to_thread(self._unwatch, wallet["id"], "invalid address rejected by the explorer")
                    log.warning("bitcoin address {} is invalid - unwatched", wallet["address"])
                else:
                    log.warning("bitcoin poll failed for {}: {}", wallet["address"], exc)
            await asyncio.sleep(0.5)
        for wallet in due.get("tron", []):
            try:
                account = await tronscan.account(wallet["address"])
                changed = account.transaction_count != (wallet["transaction_count"] or 0) or wallet["last_checked"] is None
                transfers = await tronscan.trc20_transfers(wallet["address"]) if changed else []
                result["new_transactions"] += await asyncio.to_thread(self._apply_tron, wallet, account, transfers, whale_usd)
                result["tron"] += 1
            except Exception as exc:  # noqa: BLE001
                result["errors"] += 1
                log.warning("tron poll failed for {}: {}", wallet["address"], exc)
        self.last_run["poll"] = utcnow()
        self.last_result["poll"] = result
        log.info("wallet poll: {}", result)
        return result

    def _load_labels_standalone(self) -> None:
        with SessionLocal() as db:
            self._load_labels(db)

    @staticmethod
    def _unwatch(wallet_id: int, reason: str) -> None:
        with SessionLocal() as db:
            row = db.get(BlockchainWallet, wallet_id)
            if row is not None:
                row.watch = False
                row.last_checked = utcnow()
                row.risk_factors = [*(row.risk_factors or []), f"unwatched: {reason}"]
                db.commit()

    @staticmethod
    def _due_wallets(batch_btc: int, batch_trx: int) -> dict[str, list[dict[str, Any]]]:
        with SessionLocal() as db:
            out: dict[str, list[dict[str, Any]]] = {}
            for chain, limit in (("bitcoin", batch_btc), ("tron", batch_trx), ("ethereum", 400)):
                rows = db.execute(
                    select(BlockchainWallet.id, BlockchainWallet.address, BlockchainWallet.transaction_count, BlockchainWallet.last_checked, BlockchainWallet.balance_native, BlockchainWallet.owner_name)
                    .where(BlockchainWallet.blockchain == chain, BlockchainWallet.watch.is_(True))
                    .order_by(BlockchainWallet.last_checked.asc().nulls_first())
                    .limit(limit)
                ).all()
                out[chain] = [dict(r._mapping) for r in rows]
            return out

    def _apply_eth_balances(self, wallets: list[dict[str, Any]], balances: dict[str, tuple[float, int]]) -> None:
        now = utcnow()
        with SessionLocal() as db:
            for wallet in wallets:
                info = balances.get(wallet["address"])
                if info is None:
                    continue
                balance, nonce = info
                row = db.get(BlockchainWallet, wallet["id"])
                if row is None:
                    continue
                if row.transaction_count is not None and (nonce != row.transaction_count or abs((row.balance_native or 0) - balance) > 1e-9):
                    row.last_active = now
                row.balance_native = balance
                row.balance_usd = usd_value(balance, "ETH", self.prices)
                row.transaction_count = nonce
                row.last_checked = now
            db.commit()

    def _apply_btc(self, wallet: dict[str, Any], stats: blockstream.BtcAddressStats, transfers: list[blockstream.BtcTransfer], whale_usd: float) -> int:
        now = utcnow()
        created = 0
        with SessionLocal() as db:
            row = db.get(BlockchainWallet, wallet["id"])
            if row is None:
                return 0
            row.balance_native = stats.balance_btc
            row.balance_usd = usd_value(stats.balance_btc, "BTC", self.prices)
            row.total_inflow_native = stats.received_btc
            row.total_outflow_native = stats.spent_btc
            row.transaction_count = stats.tx_count + stats.mempool_tx_count
            row.last_checked = now
            cluster_inputs: set[str] = set()
            for transfer in transfers:
                if transfer.timestamp and (row.last_active is None or transfer.timestamp > row.last_active):
                    row.last_active = transfer.timestamp
                sent = sum(v for a, v in transfer.inputs if a == row.address)
                received = sum(v for a, v in transfer.outputs if a == row.address)
                if sent > 0:
                    cluster_inputs |= cospend_cluster([a for a, _ in transfer.inputs])
                direction_from = row.address if sent > 0 else (transfer.inputs[0][0] if transfer.inputs else None)
                direction_to = row.address if received > 0 and sent == 0 else next((a for a, _ in transfer.outputs if a != row.address), None)
                amount = sent if sent > 0 else received
                details = {"inputs": len(transfer.inputs), "outputs": len(transfer.outputs), "total_out_btc": transfer.total_out_btc, "fee_btc": transfer.fee_btc, "counterparties": transfer.counterparties[:20], "confirmed": transfer.block_height is not None}
                if self._record(db, "bitcoin", transfer.txid, transfer.timestamp, transfer.block_height, direction_from, direction_to, amount, "BTC", whale_usd, details, force=True):
                    created += 1
            if cluster_inputs and len(cluster_inputs) > 1:
                self._upsert_cluster(db, "bitcoin", row, cluster_inputs)
            db.commit()
        return created

    def _apply_tron(self, wallet: dict[str, Any], account: tronscan.TronAccount, transfers: list[tronscan.TronTransfer], whale_usd: float) -> int:
        now = utcnow()
        created = 0
        with SessionLocal() as db:
            row = db.get(BlockchainWallet, wallet["id"])
            if row is None:
                return 0
            row.balance_native = account.balance_trx
            row.balance_usd = round((usd_value(account.balance_trx, "TRX", self.prices) or 0) + account.usdt_balance, 2)
            row.transaction_count = account.transaction_count
            row.last_checked = now
            row.notes = f"USDT {account.usdt_balance:,.2f}" if account.usdt_balance else row.notes
            for transfer in transfers:
                if transfer.timestamp and (row.last_active is None or transfer.timestamp > row.last_active):
                    row.last_active = transfer.timestamp
                if self._record(db, "tron", transfer.tx_hash, transfer.timestamp, transfer.block, transfer.from_address, transfer.to_address, transfer.amount, transfer.token, whale_usd, {"confirmed": True}, force=True):
                    created += 1
            db.commit()
        return created

    @staticmethod
    def _upsert_cluster(db: Session, blockchain: str, wallet: BlockchainWallet, addresses: set[str]) -> None:
        cid = cluster_id(blockchain, wallet.address)
        cluster = db.execute(select(WalletCluster).where(WalletCluster.cluster_id == cid)).scalar_one_or_none()
        linked = set(cluster.linked_addresses or []) if cluster else set()
        linked |= addresses
        linked.add(wallet.address)
        linked_list = sorted(linked)[:500]
        if cluster is None:
            cluster = WalletCluster(cluster_id=cid, blockchain=blockchain, estimated_owner=wallet.owner_name, includes_sanctioned=bool(wallet.is_sanctioned), risk_score=1.0 if wallet.is_sanctioned else 0.5,
                                    evidence={"heuristic": "common-input-ownership", "seed": wallet.address})
            db.add(cluster)
        cluster.linked_addresses = linked_list
        cluster.wallet_count = len(linked_list)
        cluster.updated_at = utcnow()

    # ------------------------------------------------------- ethereum scan
    async def scan_ethereum(self) -> dict[str, Any]:
        cfg = _config()
        if not cfg.get("enabled", True) or not cfg.get("ethereum_scan_enabled", True):
            return {"skipped": "disabled"}
        if not self.labels:
            await asyncio.to_thread(self._load_labels_standalone)
        whale_usd = float(cfg.get("whale_min_usd", 5_000_000))
        whale_eth = float(cfg.get("whale_min_eth", 1000))
        latest = await self.eth.block_number()
        start = latest if self._eth_last_block is None else self._eth_last_block + 1
        if start > latest:
            return {"blocks": 0}
        start = max(start, latest - int(cfg.get("ethereum_max_catchup_blocks", 40)))
        result: dict[str, Any] = {"blocks": latest - start + 1, "native_whales": 0, "stablecoin_whales": 0, "flagged_flows": 0}
        watched = {a for (c, a), meta in self.labels.items() if c == "ethereum" and meta.get("wallet_type") in ("sanctioned", "mixer")}
        transfers: list[EthTransfer] = []
        # 1. Newest block in full (~0.7 MB): native ETH whales + any sanctioned / mixer party. Sampled, not every block.
        block = await self.eth.block(latest, full=True)
        block_ts = from_unix_seconds(int(block["timestamp"], 16)) if block else None
        if block:
            for tx in self.eth.native_transfers(block, 0.0):
                if tx.amount >= whale_eth or tx.from_address in watched or (tx.to_address or "") in watched:
                    transfers.append(tx)
                    result["native_whales"] += tx.amount >= whale_eth
        # 2. Stablecoin whales in the newest block (sampled)
        for entry in await self.eth.stablecoin_logs(latest, latest):
            if entry.amount >= whale_usd:
                entry.timestamp = block_ts
                transfers.append(entry)
                result["stablecoin_whales"] += 1
        # 3. Complete coverage where it matters: every stablecoin transfer sent by / to a sanctioned or mixer address since the last scan
        if watched:
            topics = [t for t in (topic_for(a) for a in sorted(watched)) if t]
            for kwargs in ({"from_topics": topics}, {"to_topics": topics}):
                for entry in await self.eth.stablecoin_logs(start, latest, **kwargs):
                    entry.timestamp = block_ts
                    transfers.append(entry)
                    result["flagged_flows"] += 1
        stored = await asyncio.to_thread(self._store_eth_transfers, transfers, whale_usd)
        result.update(stored)
        self._eth_last_block = latest
        self.last_run["scan"] = utcnow()
        self.last_result["scan"] = result
        if stored.get("stored"):
            log.info("ethereum scan: {}", result)
        return result

    def _store_eth_transfers(self, transfers: list[EthTransfer], whale_usd: float) -> dict[str, int]:
        stored = sanctioned = 0
        with SessionLocal() as db:
            for tx in transfers:
                row = self._record(db, "ethereum", tx.tx_hash if tx.log_index is None else f"{tx.tx_hash}:{tx.log_index}", tx.timestamp, tx.block_number, tx.from_address, tx.to_address, tx.amount, tx.token, whale_usd, {"confirmed": True})
                if row:
                    stored += 1
                    sanctioned += bool(row.involves_sanctioned)
            db.commit()
        return {"stored": stored, "sanctioned_hits": sanctioned}

    # ------------------------------------------------------- bitcoin stream
    def ensure_stream(self) -> None:
        cfg = _config()
        if not cfg.get("enabled", True) or not cfg.get("bitcoin_stream_enabled", True):
            return
        self._whale_btc = float(cfg.get("whale_min_btc", 100))
        if self.stream is None:
            self.stream = blockstream.BitcoinMempoolStream(self._on_stream_tx)
        self.stream.start()

    def _on_stream_tx(self, txid: str, total_btc: float, inputs: list[str], outputs: list[tuple[str, float]]) -> None:
        whale_btc = self._whale_btc
        labelled = [a for a in inputs + [a for a, _ in outputs] if (("bitcoin", a) in self.labels and self.labels[("bitcoin", a)].get("wallet_type") in ("sanctioned", "mixer"))]
        if total_btc >= whale_btc or labelled:
            self._stream_hits += 1
            if len(self._stream_buffer) < 500:
                self._stream_buffer.append({"txid": txid, "total_btc": total_btc, "inputs": inputs[:50], "outputs": outputs[:50], "labelled": labelled, "seen": utcnow()})

    async def flush_stream(self) -> dict[str, int]:
        cfg = _config()
        self._whale_btc = float(cfg.get("whale_min_btc", 100))
        buffer, self._stream_buffer = self._stream_buffer, []
        if not buffer:
            return {"stored": 0}
        if not self.labels:
            await asyncio.to_thread(self._load_labels_standalone)
        whale_usd = float(cfg.get("whale_min_usd", 5_000_000))

        def _store() -> int:
            stored = 0
            with SessionLocal() as db:
                for item in buffer:
                    focus = item["labelled"][0] if item["labelled"] else None
                    from_address = focus if focus in item["inputs"] else (item["inputs"][0] if item["inputs"] else None)
                    to_address = focus if focus and focus not in item["inputs"] else max(item["outputs"], key=lambda o: o[1], default=(None, 0))[0]
                    amount = sum(v for a, v in item["outputs"] if a == focus) if focus and focus not in item["inputs"] else item["total_btc"]
                    details = {"inputs": len(item["inputs"]), "outputs": len(item["outputs"]), "total_out_btc": item["total_btc"], "confirmed": False, "source": "mempool_stream"}
                    if self._record(db, "bitcoin", item["txid"], item["seen"], None, from_address, to_address, amount, "BTC", whale_usd, details, force=bool(item["labelled"])):
                        stored += 1
                db.commit()
            return stored

        stored = await asyncio.to_thread(_store)
        self.last_result["stream"] = {"buffered": len(buffer), "stored": stored}
        return {"stored": stored}

    # ------------------------------------------------------------ retention
    async def cleanup_old_data(self) -> dict[str, int]:
        days = int(config_store.get_config().get("retention", {}).get("blockchain_transactions_days", 90))
        cutoff = utcnow() - timedelta(days=days)

        def _purge() -> dict[str, int]:
            with SessionLocal() as db:
                n = db.execute(delete(BlockchainTransaction).where(BlockchainTransaction.timestamp < cutoff, BlockchainTransaction.involves_sanctioned.is_(False))).rowcount
                db.commit()
                return {"transactions": n}

        result = await asyncio.to_thread(_purge)
        log.info("retention purge: {}", result)
        return result

    # -------------------------------------------------------------- summary
    def summary(self, db: Session, hours: int = 24) -> dict[str, Any]:
        since = utcnow() - timedelta(hours=hours)
        wallets_by_chain = dict(db.execute(select(BlockchainWallet.blockchain, func.count()).where(BlockchainWallet.is_sanctioned.is_(True)).group_by(BlockchainWallet.blockchain)).all())
        sanctioned_balance = db.execute(select(func.sum(BlockchainWallet.balance_usd)).where(BlockchainWallet.is_sanctioned.is_(True))).scalar() or 0.0
        tx_by_pattern = dict(db.execute(select(BlockchainTransaction.suspicious_pattern, func.count()).where(BlockchainTransaction.timestamp >= since).group_by(BlockchainTransaction.suspicious_pattern)).all())
        volume = db.execute(select(func.sum(BlockchainTransaction.amount_usd)).where(BlockchainTransaction.timestamp >= since, BlockchainTransaction.involves_sanctioned.is_(True))).scalar() or 0.0
        active = db.execute(select(func.count(BlockchainWallet.id)).where(BlockchainWallet.is_sanctioned.is_(True), BlockchainWallet.last_active >= since)).scalar() or 0
        clusters = db.execute(select(func.count(WalletCluster.id))).scalar() or 0
        counter: Counter[str] = Counter(tx_by_pattern)
        return {
            "hours": hours,
            "sanctioned_wallets": wallets_by_chain,
            "sanctioned_wallets_total": sum(wallets_by_chain.values()),
            "sanctioned_balance_usd": round(sanctioned_balance, 2),
            "sanctioned_wallets_active": active,
            "transactions_by_pattern": dict(counter),
            "sanctioned_volume_usd": round(volume, 2),
            "clusters": clusters,
            "prices": self.prices,
            "btc_stream": self.stream.status() if self.stream else {"connected": False},
        }


blockchain_bot = BlockchainBot()
