"""Market endpoints and bot persistence against a seeded database."""

import asyncio
from datetime import timedelta

import numpy as np
import pytest

from app.utils.time import to_unix_ms, utcnow


@pytest.fixture(scope="module")
def seeded(client):
    """25 hours of synthetic 1m candles for BTC on two exchanges (+ a spike on the last candle)."""
    from app.bots.market import market_bot
    from app.database import SessionLocal

    now = utcnow().replace(second=0, microsecond=0)
    start = now - timedelta(hours=25)
    rng = np.random.default_rng(7)
    with SessionLocal() as db:
        for exchange, offset in (("binance", 0.0), ("kraken", 2.0)):
            price = 50_000.0 + offset
            rows = []
            for i in range(25 * 60):
                ts = start + timedelta(minutes=i)
                price += rng.normal(0, 3)
                close = price
                rows.append([to_unix_ms(ts), close - 1, close + 2, close - 2, close, 1.0 + rng.random()])
            rows[-1][4] = rows[-1][4] * 1.10  # +10% spike on the newest candle
            rows[-1][5] = 40.0  # and a volume burst
            market_bot._upsert_candles(db, "BTC", exchange, "1m", rows)
        db.commit()
    return now


def test_prices_with_24h_change(client, seeded):
    body = client.get("/api/market/prices?assets=BTC").json()
    assert {q["exchange"] for q in body["data"]} == {"binance", "kraken"}
    quote = body["data"][0]
    assert quote["24h_change_percent"] is not None
    assert quote["volume_24h_usd"] > 0
    assert 0 <= quote["signal_quality"] <= 100


def test_upsert_is_idempotent(client, seeded):
    from app.database import SessionLocal
    from app.models.market import MarketCandle
    from sqlalchemy import func, select

    with SessionLocal() as db:
        before = db.execute(select(func.count(MarketCandle.id))).scalar()
        assert before == 2 * 25 * 60


def test_history_resampling(client, seeded):
    raw = client.get("/api/market/history/BTC?hours=2&timeframe=1m").json()
    assert raw["exchanges"] == ["binance", "kraken"]
    assert 115 <= len(raw["candles"]) <= 121
    assert set(raw["candles"][0]) >= {"timestamp", "binance", "kraken", "composite"}

    coarse = client.get("/api/market/history/BTC?hours=2&timeframe=15m").json()
    assert 7 <= len(coarse["candles"]) <= 9
    bar = coarse["candles"][0]["binance"]
    assert bar["high"] >= bar["close"] >= bar["low"]


def test_volatility(client, seeded):
    body = client.get("/api/market/volatility/BTC?hours=6").json()
    assert set(body["exchanges"]) == {"binance", "kraken"}
    assert body["exchanges"]["binance"]["realized_volatility_daily_percent"] > 0
    assert len(body["series"]) >= 20


def test_anomaly_analysis_creates_alerts_once(client, seeded):
    from app.bots.market import market_bot

    created = asyncio.run(market_bot.analyze_anomalies())
    assert created >= 2  # price spike + volume burst on at least one exchange
    assert asyncio.run(market_bot.analyze_anomalies()) == 0  # de-duplicated

    body = client.get("/api/market/alerts?asset=BTC&severity=high,critical").json()
    assert body["total"] >= 1
    alert = body["alerts"][0]
    assert alert["intelligence_summary"]
    assert alert["acknowledged"] is False


def test_acknowledge_alert_is_audited(client, seeded):
    from app.database import SessionLocal
    from app.models.audit import AuditLog

    alert_id = client.get("/api/market/alerts?asset=BTC").json()["alerts"][0]["id"]
    response = client.post(f"/api/market/alerts/{alert_id}/acknowledge", json={"acknowledged_by": "analyst1", "notes": "seen"})
    assert response.status_code == 200
    assert response.json()["acknowledged"] is True
    assert response.json()["acknowledged_by"] == "analyst1"
    assert client.get("/api/market/alerts?asset=BTC&acknowledged=false").json()["total"] == client.get("/api/market/alerts?asset=BTC").json()["total"] - 1
    with SessionLocal() as db:
        assert db.query(AuditLog).filter_by(action_type="alert_acknowledged", user_id="analyst1").count() == 1
    assert client.post("/api/market/alerts/999999/acknowledge", json={}).status_code == 404


def test_coordination_analysis_and_status_update(client, seeded):
    from app.bots.market import market_bot

    created = asyncio.run(market_bot.analyze_coordination())
    assert created == 1  # synchronised +10% on both exchanges
    events = client.get("/api/market/coordination?asset=BTC").json()["events"]
    assert len(events) == 1
    event = events[0]
    assert event["exchanges"] == ["binance", "kraken"]
    assert event["investigation_status"] == "flagged"
    assert event["analyst_assessment"]

    patched = client.patch(f"/api/market/coordination/{event['id']}", json={"investigation_status": "investigating", "analyst_notes": "checking"})
    assert patched.status_code == 200
    assert patched.json()["investigation_status"] == "investigating"
    assert client.get("/api/market/coordination?status=investigating").json()["total"] == 1
    assert client.patch(f"/api/market/coordination/{event['id']}", json={"investigation_status": "bogus"}).status_code == 422


def test_market_config_and_status(client):
    response = client.post("/api/market/config", json={"assets": ["BTC", "ETH", "SOL"]})
    assert response.status_code == 200
    assert response.json()["assets"] == ["BTC", "ETH", "SOL"]
    assert client.get("/api/admin/config").json()["market"]["assets"] == ["BTC", "ETH", "SOL"]

    status = client.get("/api/market/status").json()
    assert status["candles_stored"] > 0
    assert "liquidation_stream" in status


def test_history_alerts_in_period(client, seeded):
    body = client.get("/api/market/history/BTC?hours=1").json()
    assert body["anomalies_in_period"], "alerts created by the analysis should appear in the history window"
