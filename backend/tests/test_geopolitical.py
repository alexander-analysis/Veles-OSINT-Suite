"""Geopolitical event monitor: classification, storage/dedup, correlation and API."""

from datetime import timedelta

import pytest

from app.analysis.geopolitical import classify_text, detect_countries, detect_sectors, draft_from_article, draft_from_gdelt, relevance, severity_from_text, time_score
from app.bots.geopolitical import GeopoliticalBot, geopolitical_bot
from app.database import SessionLocal
from app.integrations.feeds import parse_feed, parse_ofac_recent_actions
from app.integrations.gdelt import GdeltEvent
from app.models.geopolitical import EventCorrelation, GeopoliticalEvent
from app.models.maritime import SanctionsBreach, Vessel
from app.models.market import MarketAlert
from app.utils.time import utcnow


@pytest.fixture(scope="module", autouse=True)
def _cleanup(client):
    """The test database is shared across modules: remove the rows seeded here so the maritime counts stay exact."""
    yield
    with SessionLocal() as db:
        db.query(EventCorrelation).delete()
        db.query(GeopoliticalEvent).delete()
        db.query(SanctionsBreach).filter(SanctionsBreach.mmsi == "273999001").delete()
        db.query(MarketAlert).filter(MarketAlert.summary.in_(["OIL +4% anomaly", "old"])).delete()
        db.query(Vessel).filter(Vessel.mmsi == "273999001").delete()
        db.commit()


def _gdelt(**overrides) -> GdeltEvent:
    base = dict(
        global_event_id="1234567890", event_date=utcnow(), root_code="19", base_code="190", event_code="190", quad_class=4, goldstein=-10.0,
        mentions=40, sources=6, articles=40, tone=-7.5, actor1="RUSSIA", actor1_country="RU", actor2="UKRAINE", actor2_country="UA",
        location="Odesa, Ukraine", country="UA", lat=46.48, lon=30.72, source_url="https://example.com/news/strike-on-odesa-port", added=utcnow(),
    )
    base.update(overrides)
    return GdeltEvent(**base)


def test_text_classification_and_countries():
    assert classify_text("OFAC designates shadow fleet tankers moving Iranian crude") == "sanctions"
    assert classify_text("Tanker seized in the Strait of Hormuz") == "maritime_incident"
    assert classify_text("Port of Novorossiysk closed after drone attack") == "port_closure"
    assert detect_countries("Russian tanker detained by Estonia near Finland") == ["EE", "FI", "RU"] or set(detect_countries("Russian tanker detained by Estonia near Finland")) == {"EE", "FI", "RU"}
    assert "energy" in detect_sectors("crude tanker") and "shipping" in detect_sectors("crude tanker")
    assert severity_from_text("Hormuz tanker attack disrupts LNG") == "critical"


def test_gdelt_draft_filters_noise_and_scores_severity():
    assert draft_from_gdelt(_gdelt(mentions=2)) is None  # below the noise floor
    assert draft_from_gdelt(_gdelt(root_code="04", base_code="040")) is None  # consult / routine diplomacy
    assert draft_from_gdelt(_gdelt(source_url="https://www.prnewswire.com/x")) is None
    draft = draft_from_gdelt(_gdelt())
    assert draft.event_type == "conflict" and draft.severity == "high" and draft.country_primary == "UA" and draft.country_secondary == "RU"
    assert draft.affected_countries == ["RU", "UA"] and 0.6 <= draft.confidence <= 0.95
    sanctions = draft_from_gdelt(_gdelt(root_code="16", base_code="163", event_code="163", mentions=35))
    assert sanctions.event_type == "sanctions" and sanctions.severity == "high" and sanctions.market_impact
    critical = draft_from_gdelt(_gdelt(mentions=80))
    assert critical.severity == "critical"


def test_article_draft_from_topic():
    draft = draft_from_article("Iranian tanker seized by US Navy in the Strait of Hormuz", "https://example.com/a", utcnow(), "gdelt_doc", "maritime_incident", "example.com")
    assert draft.event_type == "maritime_incident" and draft.country_primary == "IR" and "US" in draft.affected_countries
    assert draft.severity in ("high", "critical") and draft.supply_chain_impact


def test_feed_parsers():
    rss = """<rss version="2.0"><channel><item><title>UN Security Council meets on Red Sea attacks</title><link>https://press.un.org/en/1</link>
    <pubDate>Mon, 15 Sep 2026 09:00:00 GMT</pubDate><description>&lt;p&gt;Summary&lt;/p&gt;</description><guid>sc-1</guid></item></channel></rss>"""
    items = parse_feed(rss, "un_press")
    assert len(items) == 1 and items[0].published.hour == 9 and items[0].summary == "Summary" and items[0].guid == "sc-1"
    atom = """<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>tag:1</id><title>FCDO statement on Belarus</title>
    <link rel="alternate" href="https://www.gov.uk/x"/><updated>2026-09-15T10:00:00+01:00</updated><summary>s</summary></entry></feed>"""
    entry = parse_feed(atom, "gov_uk_fcdo")[0]
    assert entry.link == "https://www.gov.uk/x" and entry.published.hour == 9  # converted to UTC
    html = '<ul><li><a href="/recent-actions/20260915" class="x">Russia-related Designations; Iran-related Designations</a></li></ul>'
    ofac = parse_ofac_recent_actions(html)
    assert ofac[0].link.endswith("/recent-actions/20260915") and ofac[0].published.day == 15


def test_store_deduplicates_and_correlates(client):
    bot = GeopoliticalBot()
    now = utcnow()
    drafts = [draft_from_gdelt(_gdelt()), draft_from_gdelt(_gdelt(global_event_id="999", mentions=12)), draft_from_gdelt(_gdelt(global_event_id="1234567890"))]
    result = bot._store(drafts)
    assert result["inserted"] == 1 and result["duplicates"] == 2  # same URL / same provider id collapse
    assert bot._store([draft_from_gdelt(_gdelt())])["inserted"] == 0
    with SessionLocal() as db:
        event = db.query(GeopoliticalEvent).filter_by(source_id="1234567890").one()
        assert event.event_type == "conflict" and event.affected_countries == ["RU", "UA"]
        vessel = Vessel(mmsi="273999001", name="TEST TANKER", flag_state="RU", ship_type="Tanker")
        db.add(vessel)
        db.flush()
        db.add(SanctionsBreach(vessel_id=vessel.id, vessel_name="TEST TANKER", mmsi=vessel.mmsi, flag="RU", breach_type="direct_match", sanctioning_authority="OFAC",
                               sanctioned_entity_name="TEST TANKER", match_confidence=0.95, severity="critical", timestamp=now + timedelta(hours=1)))
        db.add(MarketAlert(asset="OIL", alert_type="price_anomaly", severity="high", price_at_alert=90.0, timestamp=now + timedelta(hours=2), summary="OIL +4% anomaly"))
        db.add(MarketAlert(asset="BTC", alert_type="volume_spike", severity="low", price_at_alert=1.0, timestamp=now - timedelta(days=5), summary="old"))
        db.commit()
    outcome = GeopoliticalBot._correlate(window_hours=24, min_score=0.5, min_severity="medium")
    assert outcome["correlations"] >= 1
    with SessionLocal() as db:
        event = db.query(GeopoliticalEvent).filter_by(source_id="1234567890").one()
        links = db.query(EventCorrelation).filter_by(geopolitical_event_id=event.id).all()
        kinds = {link.alert_type for link in links}
        assert "sanctions_breach" in kinds and event.correlated_with_maritime and event.correlated_with_sanctions
        assert all(link.correlation_score >= 0.5 for link in links)
        assert all(link.alert_type != "market_alert" or link.alert_id != 0 for link in links)
    # a second pass must not duplicate links
    assert GeopoliticalBot._correlate(window_hours=24, min_score=0.5, min_severity="medium")["correlations"] == 0


def test_relevance_and_time_score():
    score, keys = relevance(["energy", "shipping"], ["RU"], "sanctions", {"kind": "sanctions_breach", "sector": "shipping", "countries": ["RU"]})
    assert score == 1.0 and "country:RU" in keys and "theme:sanctions" in keys
    assert relevance(["finance"], [], "political", {"kind": "evasion_event", "sector": "shipping", "countries": []})[0] == 0
    now = utcnow()
    assert time_score(now, now + timedelta(hours=12), 24) == 0.5 and time_score(now, now + timedelta(hours=30), 24) == 0


def test_geopolitical_api(client):
    events = client.get("/api/geopolitical/events?hours=48&min_severity=medium").json()
    assert events["total"] >= 1 and events["events"][0]["event_date"].endswith("Z")
    event_id = events["events"][0]["id"]
    detail = client.get(f"/api/geopolitical/events/{event_id}").json()
    assert detail["id"] == event_id and isinstance(detail["correlations"], list)
    assert client.get("/api/geopolitical/events?country=ua&hours=48").json()["total"] >= 1
    assert client.get("/api/geopolitical/events?country=zz&hours=48").json()["total"] == 0
    assert client.get("/api/geopolitical/alerts").json()["total"] >= 1
    assert client.get("/api/geopolitical/correlations").json()["total"] >= 1
    timeline = client.get("/api/geopolitical/timeline/UA?days=7").json()
    assert timeline["total"] >= 1 and timeline["buckets"][0]["total"] >= 1
    assert client.get("/api/geopolitical/timeline/ukraine").status_code == 400
    geo = client.get("/api/geopolitical/geojson?hours=48").json()
    assert geo["type"] == "FeatureCollection" and geo["features"][0]["geometry"]["coordinates"] == [30.72, 46.48]
    summary = client.get("/api/geopolitical/summary?hours=48").json()
    assert summary["total"] >= 1 and summary["by_type"].get("conflict", 0) >= 1
    verified = client.post(f"/api/geopolitical/events/{event_id}/verify", json={"status": "confirmed", "notes": "matches OSINT footage", "analyst": "alex"}).json()
    assert verified["verification_status"] == "confirmed" and "matches OSINT footage" in verified["intelligence_notes"]
    assert client.get("/api/geopolitical/status").status_code == 200
    assert client.get("/api/geopolitical/sources").status_code == 200
    assert geopolitical_bot.summary  # exported singleton
