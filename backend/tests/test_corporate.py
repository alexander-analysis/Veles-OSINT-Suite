"""Corporate intelligence: name matching, shell indicators, GLEIF ingestion (mocked) and API."""

import asyncio
from datetime import timedelta

import pytest

from app.analysis.corporate import assess_shell, best_match, core_name, name_similarity
from app.bots.corporate import CorporateBot
from app.database import SessionLocal
from app.integrations import gleif
from app.integrations.edgar import parse_browse_atom
from app.models.corporate import Company, OwnershipChain, Shareholder
from app.models.sanctions import SanctionsEntity
from app.utils.time import utcnow

GLEIF_ITEM = {
    "id": "391200PKEUF3Y2NUMW25",
    "attributes": {
        "lei": "391200PKEUF3Y2NUMW25",
        "entity": {
            "legalName": {"name": "Rosneft Deutschland GmbH"},
            "otherNames": [{"name": "RN Deutschland", "language": "en", "type": "TRADING_OR_OPERATING_NAME"}],
            "legalAddress": {"addressLines": ["Kurfuerstendamm 1"], "city": "Berlin", "country": "DE", "postalCode": "10719"},
            "headquartersAddress": {"country": "DE"},
            "jurisdiction": "DE",
            "status": "ACTIVE",
            "category": "GENERAL",
            "legalForm": {"id": "2HBR", "other": None},
            "creationDate": "2011-03-01T00:00:00Z",
        },
        "registration": {"status": "ISSUED"},
    },
    "relationships": {"direct-parent": {"links": {"related": "x"}}},
}


@pytest.fixture(scope="module", autouse=True)
def _cleanup(client):
    yield
    with SessionLocal() as db:
        db.query(OwnershipChain).delete()
        db.query(Shareholder).delete()
        db.query(Company).delete()
        db.query(SanctionsEntity).filter(SanctionsEntity.source_id.in_(["test-corp-1", "test-corp-2"])).delete()
        db.commit()


def test_name_matching_helpers():
    assert core_name("Rosneft Trading S.A.") == "ROSNEFT" and core_name("PAO Sovcomflot") == "SOVCOMFLOT"
    assert name_similarity("SOVCOMFLOT PAO", "Public Joint Stock Company Sovcomflot") == 1.0
    assert name_similarity("Rosneft Deutschland GmbH", "Rosneft Trading SA") < 0.9
    hit = best_match("NK Rosneft", [("Rosneft Deutschland GmbH", []), ("Neftyanaya kompaniya Rosneft PAO", ["NK Rosneft", "Rosneft Oil Company"])], 0.9)
    assert hit == (1, 1.0)
    assert best_match("Totally Different", [("Rosneft Deutschland GmbH", [])], 0.9) is None


def test_shell_assessment():
    now = utcnow()
    shell = assess_shell("VG", "LAPSED", "ACTIVE", now - timedelta(days=100), "NO_KNOWN_PERSON", "Blue Ocean Trading Ltd", 0, now, True)
    assert shell.is_shell and shell.opaque and shell.confidence >= 0.8
    assert "secrecy_jurisdiction:VG" in shell.indicators and "recently_formed" in shell.indicators and "generic_trading_name" in shell.indicators
    clean = assess_shell("DE", "ISSUED", "ACTIVE", now - timedelta(days=5000), None, "Siemens AG", 12, now, False)
    assert not clean.is_shell and clean.confidence == 0 and not clean.opaque


def test_gleif_and_edgar_parsers():
    record = gleif.parse_record(GLEIF_ITEM)
    assert record.lei == "391200PKEUF3Y2NUMW25" and record.country == "DE" and record.other_names == ["RN Deutschland"] and record.creation_date.year == 2011
    assert record.address == "Kurfuerstendamm 1, 10719" and record.registration_status == "ISSUED"
    atom = """<?xml version="1.0" encoding="ISO-8859-1" ?><feed xmlns="http://www.w3.org/2005/Atom"><company-info><cik>0001040970</cik>
    <conformed-name>ROSNEFTEGAZSTROY   /FI</conformed-name><assigned-sic-desc>OIL &amp; GAS</assigned-sic-desc><state-location>I9</state-location>
    <addresses><address type="business"><street1>1 Main St</street1><city>Moscow</city></address></addresses></company-info></feed>"""
    hits = parse_browse_atom(atom)
    assert hits[0].cik == "1040970" and hits[0].name == "ROSNEFTEGAZSTROY /FI" and hits[0].sic_description == "OIL & GAS" and hits[0].business_address == "1 Main St, Moscow"


def test_seed_and_ingest_with_mocked_gleif(client, monkeypatch):
    with SessionLocal() as db:
        db.add(SanctionsEntity(designating_authority="OFAC", source_id="test-corp-1", name="NEFTYANAYA KOMPANIYA ROSNEFT PAO", name_normalized="NEFTYANAYA KOMPANIYA ROSNEFT PAO", entity_type="company",
                               programs=["RUSSIA-EO14024"], country_linked="RU", is_active=True, aliases=["ROSNEFT OIL COMPANY"]))
        db.add(SanctionsEntity(designating_authority="OFAC", source_id="test-corp-2", name="SHADOW TANKER 1", name_normalized="SHADOW TANKER 1", entity_type="vessel", imo="9999991",
                               vessel_owner="Blue Ocean Trading Ltd", is_active=True))
        db.commit()
    bot = CorporateBot()
    seeded = bot._seed()
    assert seeded["inserted"] >= 2
    with SessionLocal() as db:
        rosneft = db.query(Company).filter_by(name_normalized="NEFTYANAYA KOMPANIYA ROSNEFT PAO").one()
        owner = db.query(Company).filter_by(name_normalized="BLUE OCEAN TRADING LTD").one()
        assert rosneft.linked_to_sanctioned and rosneft.sanctions_match_type == "direct" and rosneft.origin == "sanctions_seed"
        assert owner.sanctions_match_type == "vessel_owner" and owner.origin == "vessel_owner"
        rosneft_id, owner_id = rosneft.id, owner.id
    assert bot._seed()["inserted"] == 0  # idempotent

    # --- mocked GLEIF: the seed matches the Russian parent (via an English other name); it has one German subsidiary
    parent_item = {
        "id": "253400JT3MQWNDKMJE44",
        "attributes": {"lei": "253400JT3MQWNDKMJE44", "entity": {"legalName": {"name": "публичное акционерное общество Роснефть"}, "otherNames": [{"name": "Rosneft Oil Company", "language": "en"}, {"name": "NK Rosneft PAO", "language": "en"}],
                       "legalAddress": {"addressLines": ["Sofiyskaya nab. 26/1"], "city": "Moscow", "country": "RU"}, "jurisdiction": "RU", "status": "ACTIVE", "category": "GENERAL", "legalForm": {"id": "X"}, "creationDate": "1993-01-01T00:00:00Z"},
                       "registration": {"status": "ISSUED"}},
    }
    parent_record = gleif.parse_record(parent_item)
    child_record = gleif.parse_record(GLEIF_ITEM)
    shell_item = {"id": "5493001KJTIIGC8Y1R12", "attributes": {"lei": "5493001KJTIIGC8Y1R12", "entity": {"legalName": {"name": "Blue Ocean Trading Ltd"}, "legalAddress": {"city": "Road Town", "country": "VG"}, "jurisdiction": "VG", "status": "ACTIVE",
                  "category": "GENERAL", "legalForm": {"id": "X"}, "creationDate": (utcnow() - timedelta(days=90)).strftime("%Y-%m-%dT00:00:00Z")}, "registration": {"status": "LAPSED"}}}
    shell_record = gleif.parse_record(shell_item)

    async def fake_search(name, limit=10, fulltext=False):
        if "ROSNEFT" in name.upper():
            return [parent_record]
        if "BLUE OCEAN" in name.upper():
            return [shell_record]
        return []

    async def fake_parent(lei, ultimate=False):
        if lei == child_record.lei:
            return parent_record
        if lei == shell_record.lei:
            return gleif.ReportingException("DIRECT_ACCOUNTING_CONSOLIDATION_PARENT", "NO_KNOWN_PERSON")
        return gleif.ReportingException("DIRECT_ACCOUNTING_CONSOLIDATION_PARENT", "NON_CONSOLIDATING")

    async def fake_children(lei, limit=50, ultimate=False):
        return [child_record] if lei == parent_record.lei else []

    async def fake_edgar(name, count=5):
        return []

    monkeypatch.setattr(gleif, "search", fake_search)
    monkeypatch.setattr(gleif, "parent", fake_parent)
    monkeypatch.setattr(gleif, "children", fake_children)
    monkeypatch.setattr("app.integrations.edgar.lookup_company", fake_edgar)

    outcome = asyncio.run(bot.enrich_one(rosneft_id, "NEFTYANAYA KOMPANIYA ROSNEFT PAO"))
    assert outcome["matched"] == 1 and outcome["exposure"] == 1  # the German subsidiary is now exposure
    with SessionLocal() as db:
        rosneft = db.get(Company, rosneft_id)
        assert rosneft.lei == "253400JT3MQWNDKMJE44" and rosneft.registration_country == "RU" and rosneft.company_name == "NEFTYANAYA KOMPANIYA ROSNEFT PAO"
        child = db.query(Company).filter_by(lei="391200PKEUF3Y2NUMW25").one()
        assert child.linked_to_sanctioned and child.sanctions_match_type == "parent" and child.origin == "ownership_walk" and child.sanctioned_entity_id == rosneft.sanctioned_entity_id
        link = db.query(Shareholder).filter_by(company_id=child.id).one()
        assert link.shareholder_company_id == rosneft.id and link.is_sanctioned and link.relationship_type == "direct_parent"
        chain = db.query(OwnershipChain).filter_by(subsidiary_id=rosneft.id).one()
        assert chain.involves_sanctioned and chain.chain_length == 0
        child_id = child.id

    shell_outcome = asyncio.run(bot.enrich_one(owner_id, "Blue Ocean Trading Ltd"))
    assert shell_outcome["matched"] == 1
    with SessionLocal() as db:
        owner = db.get(Company, owner_id)
        assert owner.lei == "5493001KJTIIGC8Y1R12" and owner.is_shell_company and owner.ownership_opaque and owner.parent_reporting_exception == "NO_KNOWN_PERSON"
        assert "secrecy_jurisdiction:VG" in owner.shell_indicators and owner.risk_score >= 0.9

    # --- API
    listing = client.get("/api/corporate/companies?linked=true&sort=risk").json()
    assert listing["total"] >= 3 and listing["companies"][0]["risk_score"] >= listing["companies"][-1]["risk_score"]
    exposure = client.get("/api/corporate/exposure").json()
    assert exposure["total"] == 1 and exposure["companies"][0]["id"] == child_id
    detail = client.get(f"/api/corporate/companies/{child_id}").json()
    assert detail["parents"][0]["id"] == rosneft_id and detail["parents"][0]["linked_to_sanctioned"] and detail["gleif_url"].endswith("391200PKEUF3Y2NUMW25")
    parent_detail = client.get(f"/api/corporate/companies/{rosneft_id}").json()
    assert parent_detail["subsidiaries"][0]["id"] == child_id and parent_detail["sanctioned_entity"]["designating_authority"] == "OFAC" and parent_detail["ownership_chain"]["involves_sanctioned"]
    assert client.get("/api/corporate/companies/999999").status_code == 404
    assert client.get("/api/corporate/companies?shell=true").json()["total"] == 1
    chains = client.get("/api/corporate/chains?sanctioned_only=true").json()
    assert len(chains) >= 1
    summary = client.get("/api/corporate/summary").json()
    assert summary["exposure"] == 1 and summary["shell_companies"] == 1 and summary["with_lei"] == 3
    local = client.get("/api/corporate/search?q=rosneft&live=false").json()
    assert local["hits"] and local["hits"][0]["tracked_company_id"]
    live = client.get("/api/corporate/search?q=rosneft&live=true").json()
    assert live["live"] is True and live["hits"][0]["lei"] == "253400JT3MQWNDKMJE44" and live["hits"][0]["tracked_company_id"] == rosneft_id
    submitted = []
    monkeypatch.setattr("app.api.corporate.bot_loop.submit", lambda coro: (submitted.append(coro), coro.close()))
    assert client.post("/api/corporate/ingest", json={"lei": "391200PKEUF3Y2NUMW25"}).status_code == 202 and len(submitted) == 1
    assert client.get("/api/corporate/status").status_code == 200
