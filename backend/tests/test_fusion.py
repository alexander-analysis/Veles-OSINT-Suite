"""Cross-bot correlation engine: signal matching, clustering, composite alerts and API."""

from datetime import timedelta

import pytest

from app.analysis.correlation_engine import Signal, clusters, correlate, narrative, shared_keys, title_for
from app.bots.correlation import CorrelationEngine, collect_signals
from app.database import SessionLocal
from app.models.correlation import CompositeAlert, SignalCorrelation
from app.models.energy import DarkOilIndicator
from app.models.geopolitical import GeopoliticalEvent
from app.models.maritime import EvasionEvent, SanctionsBreach, Vessel
from app.models.market import MarketAlert
from app.utils.time import utcnow

MMSI = "273888001"


@pytest.fixture(scope="module", autouse=True)
def _cleanup(client):
    yield
    with SessionLocal() as db:
        db.query(CompositeAlert).delete()
        db.query(SignalCorrelation).delete()
        db.query(DarkOilIndicator).delete()
        db.query(GeopoliticalEvent).filter(GeopoliticalEvent.source_id == "fusion-test").delete()
        db.query(MarketAlert).filter(MarketAlert.summary == "BRENT +5% anomaly (fusion test)").delete()
        vessel = db.query(Vessel).filter_by(mmsi=MMSI).first()
        if vessel:
            db.query(SanctionsBreach).filter_by(vessel_id=vessel.id).delete()
            db.query(EvasionEvent).filter_by(vessel_id=vessel.id).delete()
            vessel.last_ais_update = utcnow() - timedelta(days=365)
            vessel.current_position_lat = vessel.current_position_lon = None
            vessel.sanctioned_status, vessel.risk_score = "clear", 0.0
        db.commit()


def _signal(kind, sid, minutes_ago, summary, severity="medium", **keys):
    s = Signal(kind, sid, utcnow() - timedelta(minutes=minutes_ago), summary, severity)
    for k, values in keys.items():
        s.add(k, *values)
    return s


def test_pairwise_and_clusters():
    breach = _signal("sanctions_breach", 1, 60, "OFAC match: DARK STAR (GA) -> DARK STAR", "critical", vessel=[MMSI], entity=["DARK STAR"], country=["GA", "RU"], sector=["shipping"])
    dark = _signal("dark_oil", 2, 30, "DARK STAR went dark after loading at Primorsk", "high", vessel=[MMSI], country=["RU"], facility=["Primorsk"], sector=["energy", "shipping"])
    market = _signal("market_alert", 3, 20, "BRENT +5% anomaly", "high", asset=["BRENT"], sector=["energy"])
    geo = _signal("geopolitical_event", 4, 90, "Drone strike on Primorsk terminal", "high", country=["RU"], sector=["energy"], facility=["Primorsk"])
    unrelated = _signal("market_alert", 5, 10, "BTC volume spike", "low", asset=["BTC"], sector=["finance"])
    score, shared = shared_keys(breach, dark)
    assert score >= 0.9 and "vessel:" + MMSI in shared
    pairs = correlate([breach, dark, market, geo, unrelated], window_hours=48, min_score=0.3)
    refs = {(p.a.ref, p.b.ref) for p in pairs} | {(p.b.ref, p.a.ref) for p in pairs}
    assert ("sanctions_breach:1", "dark_oil:2") in refs and ("dark_oil:2", "geopolitical_event:4") in refs
    assert not any("market_alert:5" in r for r in refs)  # BTC shares nothing with the shipping story
    found = clusters(pairs, min_domains=3)
    assert len(found) == 1
    cluster = found[0]
    assert set(cluster.domains) >= {"maritime", "energy", "geopolitical"} and cluster.anchor.startswith(("vessel:", "facility:", "country:"))
    assert cluster.severity == "critical" and 0 < cluster.confidence <= 1
    text = narrative(cluster)
    assert "MARITIME:" in text and "ENERGY:" in text and title_for(cluster)
    assert clusters(pairs, min_domains=5) == []


def test_engine_persists_alerts_and_api(client):
    now = utcnow()
    with SessionLocal() as db:
        vessel = Vessel(mmsi=MMSI, imo="9800001", name="DARK STAR", flag_state="GA", ship_type="Tanker", sanctioned_status="breach_ofac", risk_score=0.95, last_ais_update=now)
        db.add(vessel)
        db.flush()
        db.add(SanctionsBreach(vessel_id=vessel.id, vessel_name="DARK STAR", mmsi=MMSI, flag="GA", breach_type="direct_match", sanctioning_authority="OFAC", sanctioned_entity_name="DARK STAR", match_confidence=0.95, severity="critical", timestamp=now - timedelta(hours=3)))
        db.add(EvasionEvent(vessel_id=vessel.id, mmsi=MMSI, event_type="ais_gap", severity="high", confidence_score=0.8, timestamp=now - timedelta(hours=2), details={"gap_hours": 14}, summary="DARK STAR AIS gap 14 h"))
        db.add(DarkOilIndicator(tanker_id=vessel.id, tanker_name="DARK STAR", mmsi=MMSI, detected_pattern="ais_gap_after_loading", suspected_origin="RU", evidence={"facility": "Primorsk crude terminal"}, confidence_score=0.9, severity="critical",
                                summary="DARK STAR went dark for 14 h after loading at Primorsk", detected_at=now - timedelta(hours=1)))
        db.add(GeopoliticalEvent(event_type="infrastructure", title="Drone strike halts loading at Primorsk", country_primary="RU", event_date=now - timedelta(hours=4), severity="high", source="gdelt_doc", source_id="fusion-test",
                                 source_urls=["https://example.com/primorsk"], affected_sectors=["energy", "shipping"], affected_countries=["RU", "UA"], confidence_score=0.6))
        db.add(MarketAlert(asset="BRENT", alert_type="price_anomaly", severity="high", price_at_alert=95.0, price_change_percent=5.0, timestamp=now - timedelta(minutes=30), summary="BRENT +5% anomaly (fusion test)"))
        db.commit()
    with SessionLocal() as db:
        signals = collect_signals(db, now - timedelta(hours=12))
        types = {s.type for s in signals}
        assert {"sanctions_breach", "evasion_event", "dark_oil", "geopolitical_event", "market_alert"} <= types
    engine = CorrelationEngine()
    result = engine._run(window_hours=48, min_score=0.3, min_domains=3)
    assert result["new_pairs"] >= 3 and result["new_alerts"] >= 1 and result["by_domain"]["maritime"] >= 2
    again = engine._run(window_hours=48, min_score=0.3, min_domains=3)
    assert again["new_pairs"] == 0 and again["new_alerts"] == 0  # idempotent
    with SessionLocal() as db:
        alert = db.query(CompositeAlert).order_by(CompositeAlert.id.desc()).first()
        assert {"maritime", "energy", "geopolitical"} <= set(alert.domains) and alert.severity in ("high", "critical") and alert.fingerprint
        assert any(s["type"] == "dark_oil" for s in alert.signals) and "Primorsk" in alert.intelligence_summary
        alert_id = alert.id

    # --- API
    queue = client.get("/api/fusion/queue?hours=12&min_severity=medium").json()
    assert queue["total"] >= 4 and queue["items"][0]["severity"] == "critical" and queue["items"][0]["correlations"] >= 1 and queue["by_domain"]["maritime"] >= 2
    assert client.get("/api/fusion/queue?hours=12&domains=market").json()["by_domain"] == {"market": 1}
    alerts = client.get("/api/fusion/composite-alerts?acknowledged=false").json()
    assert alerts and alerts[0]["id"] == alert_id and alerts[0]["window_start"].endswith("Z")
    detail = client.get(f"/api/fusion/composite-alerts/{alert_id}").json()
    assert len(detail["signals"]) >= 3
    acked = client.post(f"/api/fusion/composite-alerts/{alert_id}/acknowledge?analyst=alex").json()
    assert acked["acknowledged"] is True and acked["acknowledged_by"] == "alex"
    assert client.get("/api/fusion/composite-alerts/999999").status_code == 404
    pairs = client.get("/api/fusion/correlations?hours=12&min_confidence=0.3").json()
    assert pairs and pairs[0]["confidence"] >= 0.3 and pairs[0]["shared_keys"]
    assert client.get("/api/fusion/correlations?hours=12&signal_type=dark_oil").json()
    timeline = client.get("/api/fusion/timeline?hours=12").json()
    assert timeline["buckets"] and "maritime" in timeline["domains"]
    summary = client.get("/api/fusion/summary?hours=12").json()
    assert summary["composite_alerts"] >= 1 and summary["correlations"] >= 3 and summary["stored_alerts_total"] >= 1
    assert client.get("/api/fusion/status").status_code == 200
