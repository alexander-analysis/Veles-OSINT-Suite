"""Tier 2 / 3 bots: aviation, leaks, narratives, infra, legal (network mocked) and their APIs."""

import asyncio
from datetime import timedelta

import pytest

from app.analysis.tier2 import CompanyIndex, breach_relevance, cluster_narratives, infra_risk, narrative_assessment, parse_aircraft_remarks, registration_country
from app.bots.aviation import AviationBot
from app.bots.infra import InfraBot
from app.bots.leaks import LeaksBot
from app.bots.legal import LegalBot
from app.bots.narratives import NarrativeBot
from app.database import SessionLocal
from app.integrations import adsb, infra, leaks, legal
from app.integrations.infra import extract_domains
from app.integrations.legal import parse_courtlistener, parse_ofac_penalties
from app.models.corporate import Company
from app.models.geopolitical import GeopoliticalEvent
from app.models.maritime import Vessel
from app.models.sanctions import SanctionsEntity
from app.models.tier2 import Aircraft, AircraftSighting, BreachEvent, InfraAsset, LegalEvent, Narrative
from app.utils.time import utcnow


@pytest.fixture(scope="module", autouse=True)
def _cleanup(client):
    yield
    with SessionLocal() as db:
        db.query(AircraftSighting).delete()
        db.query(Aircraft).delete()
        db.query(BreachEvent).delete()
        db.query(Narrative).delete()
        db.query(InfraAsset).delete()
        db.query(LegalEvent).delete()
        db.query(GeopoliticalEvent).filter(GeopoliticalEvent.source_id.like("t2-%")).delete(synchronize_session=False)
        db.query(Company).filter(Company.source_ref == "t2").delete()
        db.query(SanctionsEntity).filter(SanctionsEntity.source_id.in_(["t2-air", "t2-web"])).delete(synchronize_session=False)
        db.commit()


def test_rules():
    assert registration_country("EP-GOL") == "IR" and registration_country("RA-96022") == "RU" and registration_country("N123AB") == "US" and registration_country("ZZ-1") is None
    parsed = parse_aircraft_remarks("Aircraft Model IL-76TD; Aircraft Operator YAS AIR; Aircraft Manufacturer's Serial Number (MSN) 1013409297; Aircraft Mode S Transponder Code 7301A2; Aircraft Tail Number EP-GOL")
    assert parsed == {"model": "IL-76TD", "operator": "YAS AIR", "msn": "1013409297", "mode_s": "7301A2", "tail": "EP-GOL"}
    index = CompanyIndex([(1, "Public Joint Stock Company Sovcomflot", "RU"), (2, "APOLLO", "RU"), (3, "Rice Lake Weighing Systems, Inc.", "US")])
    assert index.match("Sovcomflot PAO", "RU") == (1, "strong")
    assert index.match("Apollo", "US") == (2, "weak") and index.match("Apollo", "RU") == (2, "strong") and index.match("Totally Other", "US") == (None, "none")
    rel = breach_relevance("Black Sea Shipping Ltd", "bss.ua", "UA", "Transportation/Logistics", False, False, ["shipping"])
    assert rel.relevance == "watch_keyword" and rel.severity in ("high", "critical") and any("critical sector" in r for r in rel.reasons)
    assert breach_relevance("Local Bakery", None, "FR", "Food", False, False, []).relevance == "general"
    now = utcnow()
    items = [
        {"title": "Massive Ukrainian drone attack on Taganrog repelled, ministry says", "outlet": "tass", "time": now, "url": "u1", "countries": ["RU"]},
        {"title": "Ukrainian drone attack on Taganrog: aftermath in pictures", "outlet": "rt", "time": now, "url": "u2", "countries": ["RU"]},
        {"title": "Taganrog drone attack kills three, governor says", "outlet": "tass", "time": now, "url": "u3", "countries": ["RU"]},
        {"title": "Central bank keeps rate unchanged", "outlet": "tass", "time": now, "url": "u4", "countries": []},
    ]
    found = cluster_narratives(items, min_items=3)
    assert len(found) == 1 and found[0].outlets == {"tass": 2, "rt": 1} and "taganrog" in found[0].keywords
    score, divergence, severity, _ = narrative_assessment(found[0], 0)
    assert divergence == "state_only" and score >= 0.8 and severity == "high"
    assert narrative_assessment(found[0], 5)[1] == "mirrored"
    risk, findings = infra_risk("GoDaddy", "US", True, 30, ["ns1.cloudflare.com"], True)
    assert risk >= 0.8 and any("provider exposure" in f for f in findings) and "behind Cloudflare" in findings
    assert extract_domains("SWIFT/BIC HAVIGB2L; Website www.havanaintbank.co.uk; alt. Website https://www.hib.uk.com/; Company Number 01074897") == ["havanaintbank.co.uk", "hib.uk.com"]


def test_parsers():
    ofac_html = '<table><tr><th>x</th></tr><tr><td><a href="/media/1/download?inline"><strong>09/10/2026</strong></a></td><td>An Individual</td><td><p>1</p></td><td><p>1,427,230</p></td></tr></table>'
    rows = parse_ofac_penalties(ofac_html)
    assert rows[0].penalty_usd == 1427230 and rows[0].event_date.month == 9 and rows[0].url == "https://ofac.treasury.gov/media/1/download?inline"
    cl = parse_courtlistener({"results": [{"docket_id": 5, "caseName": "A v. ISLAMIC REPUBLIC OF IRAN", "docketNumber": "1:26-cv-1", "court": "DC", "dateFiled": "2026-03-31", "docket_absolute_url": "/docket/5/", "party": ["BANK MARKAZI"]}]}, "Bank Markazi")
    assert cl[0].source_id == "5" and cl[0].parties == ["BANK MARKAZI"] and cl[0].url.endswith("/docket/5/")
    sighting = adsb._parse_adsb_lol({"hex": "7301a2", "r": "EP-GOL", "flight": "IRY123 ", "alt_baro": 31000, "gs": 420, "track": 270, "lat": 35.5, "lon": 51.2, "seen_pos": 5, "t": "IL76"}, 1_789_000_000_000)
    assert sighting.registration == "EP-GOL" and sighting.altitude_ft == 31000 and sighting.callsign == "IRY123" and sighting.on_ground is False
    ground = adsb._parse_adsb_lol({"hex": "7301a2", "alt_baro": "ground", "lat": 1, "lon": 2}, None)
    assert ground.on_ground is True and ground.altitude_ft is None
    hibp = leaks.parse_hibp([{"Name": "Acme", "Title": "Acme Corp", "Domain": "acme.io", "BreachDate": "2026-01-02", "PwnCount": 12000000, "DataClasses": ["Passwords"], "Description": "x"}])
    assert hibp[0].records_affected == 12000000 and hibp[0].event_date.day == 2
    rw = leaks.parse_ransomware([{"victim": "Port Authority X", "group_name": "lockbit", "country": "UA", "activity": "Transportation", "discovered": "2026-09-10 00:00:00.000000", "claim_url": "http://x"}])
    assert rw[0].threat_actor == "lockbit" and rw[0].country == "UA"


def test_bots_with_mocked_network(client, monkeypatch):
    now = utcnow()
    with SessionLocal() as db:
        db.add(SanctionsEntity(designating_authority="OFAC", source_id="t2-air", name="EP-GOL", name_normalized="EP GOL", entity_type="aircraft", programs=["SDGT"], is_active=True,
                               remarks="Aircraft Model IL-76TD; Aircraft Operator YAS AIR; Aircraft Manufacturer's Serial Number (MSN) 1013409297"))
        db.add(SanctionsEntity(designating_authority="OFAC", source_id="t2-web", name="HAVANA INTERNATIONAL BANK LTD", name_normalized="HAVANA INTERNATIONAL BANK LTD", entity_type="company", programs=["CUBA"], is_active=True,
                               remarks="Website www.havanaintbank.co.uk; alt. Website www.hib.uk.com"))
        db.add(Company(company_name="Black Sea Shipping Company", name_normalized="BLACK SEA SHIPPING COMPANY", registration_country="UA", linked_to_sanctioned=True, sanctions_match_type="direct", source="sanctions_list", source_ref="t2", origin="sanctions_seed"))
        for i, (title, source, kw) in enumerate([
            ("Massive Ukrainian drone attack on Taganrog repelled", "tass", ["state_media"]), ("Ukrainian drone attack on Taganrog: aftermath", "rt", ["state_media"]), ("Taganrog drone attack kills three", "tass", ["state_media"]),
            ("UN Security Council meets on shipping", "un_press", []),
        ]):
            db.add(GeopoliticalEvent(event_type="conflict", title=title, event_date=now - timedelta(hours=i), detected_date=now, severity="medium", source=source, source_id=f"t2-{i}", source_urls=[f"https://x/{i}"], keywords=kw, affected_countries=["RU"]))
        db.commit()

    # --- aviation
    aviation = AviationBot()
    assert aviation._sync()["added"] >= 1

    async def fake_reg(registration):
        if registration == "EP-GOL":
            return [adsb.Sighting("EP-GOL", "7301a2", now, 35.5, 51.2, 31000, 420, 270, "IRY123", "2000", False, "adsb_lol", "IL76", {})]
        return []

    async def fake_hexes(hexes):
        return [adsb.Sighting(None, "7301a2", now + timedelta(minutes=5), 35.6, 51.3, 32000, 425, 271, "IRY123", "2000", False, "adsb_lol", None, {})]

    async def fake_opensky(hexes):
        return []

    monkeypatch.setattr(adsb, "lookup_registration", fake_reg)
    monkeypatch.setattr(adsb, "lookup_hexes", fake_hexes)
    monkeypatch.setattr(adsb, "opensky_states", fake_opensky)
    sweep = asyncio.run(aviation.sweep())
    assert sweep["airborne"] == 1 and sweep["sightings"] == 1
    hexes = asyncio.run(aviation.poll_hexes())
    assert hexes["hexes"] >= 1 and hexes["sightings"] == 1
    with SessionLocal() as db:
        plane = db.query(Aircraft).filter_by(registration="EP-GOL").one()
        assert plane.icao_hex == "7301a2" and plane.sightings_count == 2 and plane.last_callsign == "IRY123" and plane.country == "IR" and plane.operator == "YAS AIR"
        plane_id = plane.id

    # --- leaks
    async def fake_rw():
        return leaks.parse_ransomware([{"victim": "Black Sea Shipping Company", "group_name": "lockbit", "country": "UA", "activity": "Transportation/Logistics", "discovered": "2026-09-10 00:00:00.000000", "claim_url": "http://x"},
                                       {"victim": "Corner Bakery", "group_name": "play", "country": "FR", "activity": "Food", "discovered": "2026-09-10 00:00:00.000000"}])

    async def fake_hibp():
        return []

    monkeypatch.setattr(leaks, "fetch_ransomware_recent", fake_rw)
    monkeypatch.setattr(leaks, "fetch_hibp_breaches", fake_hibp)
    result = asyncio.run(LeaksBot().fetch())
    assert result["inserted"] == 1 and result["below_threshold"] == 1
    with SessionLocal() as db:
        breach = db.query(BreachEvent).one()
        assert breach.relevance == "tracked_company" and breach.matched_company_id and breach.severity in ("high", "critical")

    # --- narratives
    result = asyncio.run(NarrativeBot().run())
    assert result["created"] == 1
    with SessionLocal() as db:
        narrative = db.query(Narrative).one()
        assert narrative.divergence == "state_only" and narrative.outlet_count == 2 and "taganrog" in narrative.keywords

    # --- infra
    infra_bot = InfraBot()
    assert infra_bot._seed()["added"] >= 2

    async def fake_footprint(domain):
        record = infra.DomainRecord(domain=domain, registrar="Team Blue", resolves_to=["185.1.2.3"] if domain == "hib.uk.com" else [], is_live=domain == "hib.uk.com", asn="AS8622", asn_org="Scarlet", hosting_country="GB", certificate_count=3, certificate_names=[f"mail.{domain}"])
        return record

    monkeypatch.setattr(infra, "footprint", fake_footprint)
    fp = asyncio.run(infra_bot.footprint())
    assert fp["checked"] >= 2 and fp["live"] == 1
    with SessionLocal() as db:
        live = db.query(InfraAsset).filter_by(value="hib.uk.com").one()
        assert live.is_live and live.hosting_country == "GB" and live.risk_score >= 0.7 and live.entity_name.startswith("HAVANA")

    # --- legal
    async def fake_penalties():
        return [legal.LegalRecord("ofac_enforcement", "09/10/2026:An Individual", "OFAC enforcement: An Individual (09/10/2026)", "https://ofac.treasury.gov/x", "OFAC", now, "enforcement", "1 penalty", 1427230.0, ["An Individual"])]

    async def fake_doj(keywords=()):
        return []

    async def fake_cl(query, result_type="r"):
        return [legal.LegalRecord("courtlistener", "77", "ESTATE OF X v. HAVANA INTERNATIONAL BANK LTD", "https://www.courtlistener.com/docket/77/", "DC", now, "docket", "1:26-cv-1", None, ["HAVANA INTERNATIONAL BANK LTD"], {"query": query}),
                legal.LegalRecord("courtlistener", "78", "UNRELATED v. SOMEONE", "https://www.courtlistener.com/docket/78/", "DC", now, "docket", "1:26-cv-2", None, ["SOMEONE"], {"query": query})]

    monkeypatch.setattr(legal, "fetch_ofac_penalties", fake_penalties)
    monkeypatch.setattr(legal, "fetch_doj", fake_doj)
    monkeypatch.setattr(legal, "search_courtlistener", fake_cl)
    legal_bot = LegalBot()
    assert asyncio.run(legal_bot.fetch_official())["inserted"] == 1
    monkeypatch.setattr(LegalBot, "_query_names", staticmethod(lambda: [(db_entity_id("t2-web"), "HAVANA INTERNATIONAL BANK LTD")]))
    dockets = asyncio.run(legal_bot.search_dockets())
    assert dockets["queries"] == 1 and dockets["hits"] == 1  # the unrelated docket is filtered out
    with SessionLocal() as db:
        match = db.query(LegalEvent).filter_by(source="courtlistener").one()
        assert match.matched_entity_name == "HAVANA INTERNATIONAL BANK LTD" and match.relevance_score == 0.9

    # --- APIs
    assert client.get("/api/aviation/aircraft?seen_days=1").json()[0]["registration"] == "EP-GOL"
    assert len(client.get(f"/api/aviation/aircraft/{plane_id}/sightings").json()) == 2
    assert client.get("/api/aviation/geojson?hours=24").json()["features"][0]["properties"]["callsign"] == "IRY123"
    assert client.get("/api/aviation/aircraft/999999/sightings").status_code == 404
    added = client.post("/api/aviation/aircraft", json={"registration": "t7-abc", "operator": "Test Jet", "analyst": "alex"}).json()
    assert added["registration"] == "T7-ABC" and added["watch"] is True
    assert client.get("/api/aviation/summary").json()["aircraft"] >= 2
    events = client.get("/api/leaks/events?days=30&relevance=tracked_company").json()
    assert events and events[0]["victim_name"] == "Black Sea Shipping Company" and events[0]["discovered_at"].endswith("Z")
    assert client.get("/api/leaks/summary").json()["tracked_company_hits"] == 1
    assert client.get("/api/narratives/?days=7").json()[0]["divergence"] == "state_only"
    assert client.get("/api/narratives/summary").json()["narratives"] == 1
    assets = client.get("/api/infra/assets?live=true").json()
    assert assets[0]["value"] == "hib.uk.com" and client.get("/api/infra/summary").json()["live"] == 1
    assert client.get("/api/legal/events?matched_only=true").json()[0]["source"] == "courtlistener"
    assert client.get("/api/legal/summary").json()["penalties_usd"] == 1427230
    for path in ("/api/aviation/status", "/api/leaks/status", "/api/narratives/status", "/api/infra/status", "/api/legal/status"):
        assert client.get(path).status_code == 200


def db_entity_id(source_id: str) -> int:
    with SessionLocal() as db:
        return db.query(SanctionsEntity.id).filter_by(source_id=source_id).scalar()


def test_psc_monitor(client, monkeypatch):
    from app.bots.psc import PscBot
    from app.integrations import psc as psc_integration
    from app.integrations.psc import parse_apcis, parse_thetis_bans, parse_thetis_detentions
    from app.models.tier2 import PscEvent

    thetis = parse_thetis_detentions([{"id": 1, "imoNumber": "9700001", "shipName": "TEST SHADOW AFRA", "flag": {"code": "GA", "description": "Gabon"}, "shipType": {"description": "Oil tanker", "tanker": True},
                                       "detentionDate": "15/09/2026", "detentionPort": {"name": "Rijeka", "country": {"code": "HR", "description": "Croatia"}}, "detentionReportingAuthority": {"description": "Croatia"}}])
    assert thetis[0].imo == "9700001" and thetis[0].flag == "GA" and thetis[0].port_country == "HR" and thetis[0].event_date.day == 15
    bans = parse_thetis_bans([{"id": 2, "imoNumber": "9418286", "shipName": "SELAM", "flag": {"code": "KN"}, "ismCompany": {"name": "Unimarin Denizcilik", "imoNumber": "5322090"}, "banDate": "10/09/2026", "banReason": {"description": "Multiple detentions"}}])
    assert bans[0].event_type == "ban" and bans[0].company == "Unimarin Denizcilik"
    html = ("<table><tr><th>x</th></tr><tr><td>1</td><td>9310745</td><td>AC KATHRYN</td><td>Panama</td><td>2004-11-01</td><td>19885</td><td>Bulk carrier</td><td>NKK</td><td>NKK;</td><td>SINCERE INDUSTRIAL CORP</td>"
            "<td>Shanghai, China</td><td>01.08.2026</td><td>04.08.2026</td><td>11124 - LIFE SAVING APPLIANCES - x<br>03105 - WATERTIGHT - y</td></tr></table>")
    apcis = parse_apcis(html)
    assert apcis[0].imo == "9310745" and apcis[0].flag == "PA" and apcis[0].port == "Shanghai" and apcis[0].port_country == "CN" and len(apcis[0].deficiencies) == 2 and apcis[0].gross_tonnage == 19885

    async def fake_paris():
        return thetis, bans

    async def fake_tokyo(year, month):
        return apcis

    monkeypatch.setattr(psc_integration, "fetch_paris", fake_paris)
    monkeypatch.setattr(psc_integration, "fetch_tokyo", fake_tokyo)
    with SessionLocal() as db:
        vessel = db.query(Vessel).filter_by(imo="9700001").first()
        if vessel is None:
            vessel = Vessel(mmsi="273777001", imo="9700001", name="TEST SHADOW AFRA", flag_state="GA", ship_type="Tanker")
            db.add(vessel)
        vessel.sanctioned_status, vessel.risk_score = "flagged", 0.7
        db.commit()
    result = asyncio.run(PscBot().fetch())
    assert result["inserted"] == 3 and result["matched_vessels"] == 1 and result["flagged"] == 1
    assert asyncio.run(PscBot().fetch())["inserted"] == 0
    with SessionLocal() as db:
        flagged = db.query(PscEvent).filter_by(imo="9700001").one()
        assert flagged.vessel_flagged and flagged.relevance_score >= 0.9 and flagged.vessel_id
    rows = client.get("/api/psc/events?days=365&flagged_only=true").json()
    assert rows and rows[0]["ship_name"] == "TEST SHADOW AFRA" and rows[0]["event_date"].endswith("Z")
    assert client.get("/api/psc/events?days=365&event_type=ban").json()[0]["ship_name"] == "SELAM"
    assert client.get("/api/psc/vessel/9310745").json()[0]["port"] == "Shanghai"
    summary = client.get("/api/psc/summary?days=365").json()
    assert summary["events"] >= 3 and summary["bans_on_record"] == 1 and summary["flagged_vessels"] == 1
    assert client.get("/api/psc/status").status_code == 200
    dossier = client.get("/api/maritime/vessel/273777001/dossier").json()
    assert dossier["vessel"]["imo"] == "9700001" and dossier["port_state_control"][0]["port"] == "Rijeka" and dossier["port_state_control"][0]["event_type"] == "detention"
    assert isinstance(dossier["shipments"], list) and isinstance(dossier["fusion_links"], list) and dossier["listings_by_imo"] == []
    assert client.get("/api/maritime/vessel/000000000/dossier").status_code == 404
    pdf = client.get("/api/maritime/vessel/273777001/dossier?format=pdf&classification=CONFIDENTIAL")
    assert pdf.status_code == 200 and pdf.headers["content-type"] == "application/pdf" and pdf.content[:4] == b"%PDF" and len(pdf.content) > 2000
    with SessionLocal() as db:
        db.query(PscEvent).delete()
        vessel = db.query(Vessel).filter_by(imo="9700001").first()
        if vessel:
            vessel.sanctioned_status, vessel.risk_score = "clear", 0.0
        db.commit()


def test_entity_dossier(client):
    from app.models.blockchain import BlockchainTransaction, BlockchainWallet

    with SessionLocal() as db:
        entity = SanctionsEntity(designating_authority="OFAC", source_id="t2-dossier", name="TEST DOSSIER HOLDINGS LLC", name_normalized="TEST DOSSIER HOLDINGS LLC", entity_type="company", programs=["RUSSIA-EO14024"], is_active=True, first_seen_at=utcnow(), last_updated=utcnow())
        db.add(entity)
        db.flush()
        db.add(SanctionsEntity(designating_authority="EU", source_id="t2-dossier-eu", name="TEST DOSSIER HOLDINGS LLC", name_normalized="TEST DOSSIER HOLDINGS LLC", entity_type="company", programs=["UKR"], is_active=True, first_seen_at=utcnow(), last_updated=utcnow()))
        db.add(Company(company_name="TEST DOSSIER HOLDINGS LLC", lei="TESTDOSSIER000000001", registration_country="AE", sanctioned_entity_id=entity.id, sanctions_match_type="direct", risk_score=0.9, source="gleif", source_ref="t2"))
        db.add(BlockchainWallet(blockchain="tron", address="TDossierTestWallet00000000000000001", owner_entity_id=entity.id, balance_usd=1500.5, transaction_count=3, sanctioning_authority="OFAC", owner_name=entity.name, is_sanctioned=True))
        db.add(BlockchainTransaction(blockchain="tron", tx_hash="dossier-tx-1", timestamp=utcnow(), from_address="TDossierTestWallet00000000000000001", to_address="TSomewhereElse", amount_usd=1200.0, token_type="USDT", suspicious_pattern="sanctioned_counterparty"))
        db.add(LegalEvent(source="doj", source_id="t2-dossier-legal", title="Test Dossier Holdings indicted", matched_entity_id=entity.id, event_type="indictment", event_date=utcnow()))
        db.add(InfraAsset(asset_type="domain", value="dossier-test.example", entity_id=entity.id, is_live=True, risk_score=0.7))
        db.add(Aircraft(registration="T7-DOS", sanctioned_entity_id=entity.id, model="Gulfstream", operator="Test Dossier Holdings"))
        db.commit()
        entity_id = entity.id
    try:
        d = client.get(f"/api/sanctions/entities/{entity_id}/dossier").json()
        assert d["entity"]["name"] == "TEST DOSSIER HOLDINGS LLC" and d["other_listings"][0]["authority"] == "EU"
        assert d["companies"][0]["lei"] == "TESTDOSSIER000000001" and d["wallets"][0]["blockchain"] == "tron" and d["wallet_balance_usd"] == 1500.5
        assert d["transfers"][0]["tx_hash"] == "dossier-tx-1" and d["transfers"][0]["timestamp"].endswith("Z")
        assert d["legal_events"][0]["event_type"] == "indictment" and d["domains"][0]["value"] == "dossier-test.example" and d["aircraft"][0]["registration"] == "T7-DOS"
        assert d["vessels"] == [] and d["ownership_chains"] == []
        assert client.get("/api/sanctions/entities/999999999/dossier").status_code == 404
        pdf = client.get(f"/api/sanctions/entities/{entity_id}/dossier?format=pdf")
        assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF" and "VELES_Entity_" in pdf.headers["content-disposition"]
    finally:
        with SessionLocal() as db:
            db.query(BlockchainTransaction).filter_by(tx_hash="dossier-tx-1").delete()
            db.query(BlockchainWallet).filter_by(address="TDossierTestWallet00000000000000001").delete()
            db.query(Aircraft).filter_by(registration="T7-DOS").delete()
            db.query(InfraAsset).filter_by(value="dossier-test.example").delete()
            db.query(LegalEvent).filter_by(source_id="t2-dossier-legal").delete()
            db.query(Company).filter_by(lei="TESTDOSSIER000000001").delete()
            db.query(SanctionsEntity).filter(SanctionsEntity.source_id.in_(["t2-dossier", "t2-dossier-eu"])).delete(synchronize_session=False)
            db.commit()


def test_global_search(client):
    with SessionLocal() as db:
        db.add(SanctionsEntity(designating_authority="OFAC", source_id="t2-search", name="SEARCHABLE TRADING FZE", name_normalized="SEARCHABLE TRADING FZE", entity_type="company", programs=["IRAN"], aliases=["STF DUBAI"], is_active=True, first_seen_at=utcnow(), last_updated=utcnow()))
        db.add(Vessel(mmsi="273777555", imo="9700555", name="SEARCHABLE STAR", flag_state="GA", ship_type="Tanker"))
        db.commit()
    try:
        r = client.get("/api/search?q=searchable").json()
        assert r["total"] >= 2 and r["groups"]["vessels"][0]["href"] == "/maritime/vessel/273777555" and r["groups"]["listings"][0]["title"] == "SEARCHABLE TRADING FZE"
        alias = client.get("/api/search?q=STF DUBAI").json()
        assert alias["groups"]["listings"][0]["title"] == "SEARCHABLE TRADING FZE"
        by_imo = client.get("/api/search?q=9700555").json()
        assert by_imo["groups"]["vessels"][0]["title"].startswith("SEARCHABLE STAR")
        assert client.get("/api/search?q=x").status_code == 422
    finally:
        with SessionLocal() as db:
            db.query(SanctionsEntity).filter_by(source_id="t2-search").delete()
            db.query(Vessel).filter_by(mmsi="273777555").delete()
            db.commit()
