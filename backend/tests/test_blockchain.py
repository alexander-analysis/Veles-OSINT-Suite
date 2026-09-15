"""Blockchain tracker: OFAC address extraction, scoring, wallet sync, transaction recording and API."""

from datetime import timedelta

import pytest

from app.analysis.blockchain import assess_transaction, detect_chain, parse_ofac_addresses, usd_value
from app.bots.blockchain import BlockchainBot, blockchain_bot
from app.database import SessionLocal
from app.integrations import blockstream, tronscan
from app.integrations.ethereum_rpc import EthereumRPC, address_from_topic, topic_for
from app.models.blockchain import BlockchainTransaction, BlockchainWallet, WalletCluster
from app.models.sanctions import SanctionsEntity
from app.utils.time import utcnow

REMARKS = (
    "Secondary sanctions risk: section 1(b) of Executive Order 13224; Digital Currency Address - XBT 12aNKp2iDKuhEde2YfPdd4DFGenRUTKupL; "
    "alt. Digital Currency Address - ETH 0x252A8BD2319d8a555b872990601221b3a2053BCE; alt. Digital Currency Address - USDT TA3941uFAvmVibSkQ6fMJXxmaSNovX86mz; "
    "alt. Digital Currency Address - USDT 0x0000000000000000000000000000000000000001; alt. Digital Currency Address - XMR 44dZUJ7w1T3fKAvFW8XyXUVoAGSbFvXef2wcbnsjNKGWYorpLJBjth5VKSFhLGkpYKJb2J341tdZHBnbpv72WL7e8zuxfR2"
)


@pytest.fixture(scope="module", autouse=True)
def _cleanup(client):
    yield
    with SessionLocal() as db:
        db.query(BlockchainTransaction).delete()
        db.query(WalletCluster).delete()
        db.query(BlockchainWallet).delete()
        db.query(SanctionsEntity).filter(SanctionsEntity.source_id == "test-crypto-1").delete()
        db.commit()


def test_parse_ofac_addresses_and_chains():
    found = parse_ofac_addresses(REMARKS)
    chains = {(a.blockchain, a.symbol) for a in found}
    assert ("bitcoin", "XBT") in chains and ("ethereum", "ETH") in chains and ("tron", "USDT") in chains and ("ethereum", "USDT") in chains and ("monero", "XMR") in chains
    eth = next(a for a in found if a.symbol == "ETH")
    assert eth.address == "0x252a8bd2319d8a555b872990601221b3a2053bce"  # normalised to lower case
    assert detect_chain("USDT", "TA3941uFAvmVibSkQ6fMJXxmaSNovX86mz") == "tron"
    assert detect_chain("BNB", "0x" + "a" * 40) == "bsc"
    assert parse_ofac_addresses(None) == []


def test_transaction_assessment():
    sanctioned = [{"wallet_type": "sanctioned", "owner_name": "BANK X"}]
    exchange = [{"wallet_type": "exchange", "owner_name": "Binance", "label": "Binance 14"}]
    a = assess_transaction(2_000_000, sanctioned, exchange, 5_000_000, "USDT")
    assert a.pattern == "exchange_cashout" and a.risk_score >= 0.95 and a.involves_sanctioned and a.involves_exchange and "BANK X" in a.summary
    b = assess_transaction(12_000_000, [], [], 5_000_000, "BTC")
    assert b.pattern == "whale_transfer" and 0.4 <= b.risk_score <= 0.8
    c = assess_transaction(1000, [], [{"wallet_type": "mixer", "label": "Tornado Cash 10 ETH"}], 5_000_000, "ETH")
    assert c.pattern == "mixer_usage" and c.involves_mixer
    assert usd_value(2, "BTC", {"BTC": 70_000}) == 140_000 and usd_value(5, "USDT", {}) == 5 and usd_value(1, "TRX", {}) is None


def test_ethereum_helpers_and_parsers():
    topic = topic_for("0x252a8bd2319d8a555b872990601221b3a2053bce")
    assert len(topic) == 66 and address_from_topic(topic) == "0x252a8bd2319d8a555b872990601221b3a2053bce"
    block = {"number": "0x10", "timestamp": "0x6a5f0000", "transactions": [{"hash": "0xabc", "from": "0xAA", "to": "0xBB", "value": hex(1500 * 10**18)}, {"hash": "0xdef", "from": "0xAA", "to": None, "value": "0x1"}]}
    whales = EthereumRPC.native_transfers(block, 1000)
    assert len(whales) == 1 and whales[0].amount == 1500 and whales[0].from_address == "0xaa"
    tx = {"txid": "t1", "status": {"confirmed": True, "block_height": 900000, "block_time": 1780000000}, "fee": 1000,
          "vin": [{"prevout": {"scriptpubkey_address": "1abc", "value": 200000000}}, {"prevout": {"scriptpubkey_address": "1def", "value": 100000000}}],
          "vout": [{"scriptpubkey_address": "3out", "value": 299999000}]}
    parsed = blockstream.parse_transaction(tx, "1abc")
    assert parsed.total_out_btc == 2.99999 and parsed.counterparties == ["1def", "3out"] and parsed.block_height == 900000


def test_wallet_sync_records_and_api(client):
    with SessionLocal() as db:
        db.add(SanctionsEntity(designating_authority="OFAC", source_id="test-crypto-1", name="TEST CRYPTO ENTITY", name_normalized="TEST CRYPTO ENTITY", entity_type="individual",
                               programs=["CYBER2"], remarks=REMARKS, is_active=True))
        db.commit()
    bot = BlockchainBot()
    result = bot._sync()
    assert result["added"] >= 5 and result["sanctioned_by_chain"].get("bitcoin", 0) >= 1 and result["sanctioned_by_chain"].get("tron", 0) >= 1
    assert ("ethereum", "0x252a8bd2319d8a555b872990601221b3a2053bce") in bot.labels
    assert ("ethereum", "0x28c6c06298d514db089934071355e5743bf21d60") in bot.labels  # curated Binance label
    assert bot._sync()["added"] == 0  # idempotent
    bot.prices.update({"BTC": 70_000.0, "ETH": 3_000.0})
    with SessionLocal() as db:
        wallet = db.query(BlockchainWallet).filter_by(blockchain="bitcoin", address="12aNKp2iDKuhEde2YfPdd4DFGenRUTKupL").one()
        assert wallet.is_sanctioned and wallet.watch and wallet.owner_name == "TEST CRYPTO ENTITY" and wallet.sanctions_programs == ["CYBER2"]
        monero = db.query(BlockchainWallet).filter_by(blockchain="monero").first()
        assert monero is not None and monero.watch is False  # stored, not pollable
        wallet_info = {"id": wallet.id, "address": wallet.address, "transaction_count": None, "last_checked": None, "balance_native": None, "owner_name": wallet.owner_name}
    stats = blockstream.BtcAddressStats(address=wallet_info["address"], received_btc=1.5, spent_btc=1.0, tx_count=3, mempool_tx_count=0)
    now = utcnow()
    transfers = [
        blockstream.BtcTransfer("tx-out", now - timedelta(hours=2), 900001, [(wallet_info["address"], 1.0), ("1cospend", 0.5)], [("34xp4vRoCGJym3xR7yCVPFHoCNxv4Twseo", 1.49)], 0.01, 1.49, ["1cospend", "34xp4vRoCGJym3xR7yCVPFHoCNxv4Twseo"]),
        blockstream.BtcTransfer("tx-in", now - timedelta(hours=5), 900000, [("1sender", 1.5)], [(wallet_info["address"], 1.5)], 0.0, 1.5, ["1sender"]),
    ]
    created = bot._apply_btc(wallet_info, stats, transfers, whale_usd=5_000_000)
    assert created == 2
    assert bot._apply_btc(wallet_info, stats, transfers, whale_usd=5_000_000) == 0  # de-duplicated by tx hash
    with SessionLocal() as db:
        out = db.query(BlockchainTransaction).filter_by(tx_hash="tx-out").one()
        assert out.involves_sanctioned and out.involves_exchange and out.suspicious_pattern == "exchange_cashout" and out.destination_entity == "Binance" and out.amount_usd == 70_000
        inbound = db.query(BlockchainTransaction).filter_by(tx_hash="tx-in").one()
        assert inbound.to_address == wallet_info["address"] and inbound.suspicious_pattern == "sanctioned_counterparty"
        cluster = db.query(WalletCluster).filter_by(blockchain="bitcoin").one()
        assert set(cluster.linked_addresses) == {wallet_info["address"], "1cospend"} and cluster.includes_sanctioned
        wallet = db.get(BlockchainWallet, wallet_info["id"])
        assert wallet.balance_native == 0.5 and wallet.balance_usd == 35_000 and wallet.transaction_count == 3
    # Tron: USDT balance rolls into the USD balance, transfers recorded
    with SessionLocal() as db:
        tron = db.query(BlockchainWallet).filter_by(blockchain="tron").first()
        tron_info = {"id": tron.id, "address": tron.address, "transaction_count": None, "last_checked": None, "balance_native": None, "owner_name": tron.owner_name}
    account = tronscan.TronAccount(address=tron_info["address"], balance_trx=10.0, usdt_balance=250_000.0, transaction_count=4, tokens={"USDT": 250_000.0})
    tron_tx = [tronscan.TronTransfer("trx-1", now - timedelta(hours=1), 1, "TSender", tron_info["address"], 250_000.0, "USDT")]
    assert bot._apply_tron(tron_info, account, tron_tx, whale_usd=5_000_000) == 1
    with SessionLocal() as db:
        tron = db.get(BlockchainWallet, tron_info["id"])
        assert tron.balance_usd == 250_000.0 and "USDT 250,000.00" in tron.notes
    # Ethereum stablecoin transfer to a mixer from a sanctioned wallet
    from app.integrations.ethereum_rpc import EthTransfer

    eth_tx = EthTransfer("0xhash", 25_000_000, now, "0x252a8bd2319d8a555b872990601221b3a2053bce", "0x910cbd523d972eb0a6f4cae4618ad62622b39dbf", 12_000.0, "USDT", log_index=3)
    stored = bot._store_eth_transfers([eth_tx], whale_usd=5_000_000)
    assert stored == {"stored": 1, "sanctioned_hits": 1}
    with SessionLocal() as db:
        row = db.query(BlockchainTransaction).filter_by(blockchain="ethereum").one()
        assert row.suspicious_pattern == "sanctioned_mixer_usage" and row.involves_mixer and row.tx_hash == "0xhash:3"

    # --- API
    wallets = client.get("/api/blockchain/wallets?sanctioned=true&chain=bitcoin").json()
    assert wallets["total"] >= 1 and wallets["wallets"][0]["owner_name"] == "TEST CRYPTO ENTITY"
    detail = client.get(f"/api/blockchain/wallets/bitcoin/{wallet_info['address']}").json()
    assert len(detail["transactions"]) == 2 and detail["cluster"]["wallet_count"] == 2 and detail["explorer_url"].startswith("https://mempool.space")
    assert client.get("/api/blockchain/wallets/bitcoin/unknown-address-xxxxxxxxxxxx").status_code == 404
    txs = client.get("/api/blockchain/transactions?hours=48&involves_sanctioned=true").json()
    assert txs["total"] == 4 and txs["transactions"][0]["timestamp"].endswith("Z")
    assert client.get("/api/blockchain/transactions?hours=48&pattern=exchange_cashout").json()["total"] == 1
    summary = client.get("/api/blockchain/summary?hours=48").json()
    assert summary["sanctioned_wallets_total"] >= 5 and summary["transactions_by_pattern"]["exchange_cashout"] == 1 and summary["clusters"] == 1
    added = client.post("/api/blockchain/wallets", json={"blockchain": "ethereum", "address": "0xABCDEFabcdef0000000000000000000000000001", "label": "Suspect hot wallet", "wallet_type": "individual", "analyst": "alex"}).json()
    assert added["address"] == "0xabcdefabcdef0000000000000000000000000001" and added["watch"] is True
    acked = client.post(f"/api/blockchain/transactions/{txs['transactions'][0]['id']}/acknowledge?analyst=alex").json()
    assert acked["acknowledged"] is True
    assert client.get("/api/blockchain/clusters").json()[0]["includes_sanctioned"] is True
    assert client.get("/api/blockchain/status").status_code == 200 and blockchain_bot.status()["labels_loaded"] >= 0
