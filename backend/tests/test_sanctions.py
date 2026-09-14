"""Sanctions importers (fixtures), list diffing, matching index and API."""

from datetime import datetime

import pytest

from app.analysis.sanctions import SanctionsIndex, compare_sanctions_lists
from app.integrations import eu_sanctions, ofac, un_sanctions
from app.integrations.sanctions_common import SanctionedEntityRecord, extract_imo, normalize_name

SDN_CSV = (
    '4238,"MAR AZUL","vessel","CUBA",-0- ,"CL2192","Tug",-0- ,"212","Cuba","Samir de Navegacion S.A.",-0- \n'
    '9001,"SHADOW STAR","vessel","RUSSIA-EO14024",-0- ,-0- ,"Crude Oil Tanker",-0- ,-0- ,"Gabon",-0- ,"Vessel Registration Identification IMO 9182253"\n'
    '9002,"DARK FLEET SHIPPING LLC","entity","UKRAINE-EO13662] [RUSSIA-EO14024] [SDGT",-0- ,-0- ,-0- ,-0- ,-0- ,-0- ,-0- ,"Registration Number 12345"\n'
    '9003,"IVANOV, Ivan","individual","RUSSIA-EO14024",-0- ,-0- ,-0- ,-0- ,-0- ,-0- ,-0- ,"DOB 01 Jan 1970"\n'
)
ALT_CSV = '9001,1,"aka","SHADOW STAR I",-0- \n9002,2,"aka","DARKFLEET",-0- \n'

EU_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<export xmlns="http://eu.europa.ec/fpi/fsd/export" generationDate="2026-08-05">
  <sanctionEntity euReferenceNumber="EU.1.1" logicalId="1">
    <regulation regulationType="regulation" publicationDate="2022-03-15" programme="RUS" logicalId="3"><publicationUrl>http://eur-lex/x</publicationUrl></regulation>
    <subjectType code="enterprise" classificationCode="E"/>
    <nameAlias wholeName="Dark Fleet Shipping LLC" strong="true" logicalId="5"/>
    <nameAlias wholeName="Darkfleet" strong="false" logicalId="6"/>
    <identification identificationTypeCode="imo" number="1234567" logicalId="7"/>
    <address city="Moscow" countryIso2Code="RU" logicalId="8"/>
  </sanctionEntity>
  <sanctionEntity euReferenceNumber="EU.2.2" logicalId="2">
    <regulation regulationType="regulation" publicationDate="2014-07-31" programme="UKR" logicalId="4"/>
    <subjectType code="person" classificationCode="P"/>
    <nameAlias wholeName="Ivan Ivanov" strong="true" logicalId="9"/>
    <citizenship countryIso2Code="RU" logicalId="10"/>
  </sanctionEntity>
</export>"""

UN_XML = b"""<CONSOLIDATED_LIST><INDIVIDUALS><INDIVIDUAL><DATAID>1</DATAID><FIRST_NAME>IVAN</FIRST_NAME><SECOND_NAME>IVANOV</SECOND_NAME>
<UN_LIST_TYPE>DPRK</UN_LIST_TYPE><REFERENCE_NUMBER>KPi.001</REFERENCE_NUMBER><LISTED_ON>2016-03-02</LISTED_ON>
<INDIVIDUAL_ALIAS><ALIAS_NAME>Vanya</ALIAS_NAME></INDIVIDUAL_ALIAS><NATIONALITY><VALUE>North Korea</VALUE></NATIONALITY></INDIVIDUAL></INDIVIDUALS>
<ENTITIES><ENTITY><DATAID>2</DATAID><FIRST_NAME>OCEAN MARITIME MANAGEMENT COMPANY</FIRST_NAME><UN_LIST_TYPE>DPRK</UN_LIST_TYPE><REFERENCE_NUMBER>KPe.020</REFERENCE_NUMBER>
<LISTED_ON>2014-07-28</LISTED_ON><COMMENTS1>Operator of vessel Chong Chon Gang. International Maritime Organization (IMO) Number: 1790183.</COMMENTS1>
<ENTITY_ALIAS><ALIAS_NAME>OMM</ALIAS_NAME></ENTITY_ALIAS></ENTITY></ENTITIES></CONSOLIDATED_LIST>"""


def test_ofac_parser():
    records = ofac.parse_sdn(SDN_CSV, ALT_CSV)
    assert len(records) == 4
    tug, tanker, company, person = records
    assert tug.entity_type == "vessel" and tug.vessel_flag == "CU" and tug.vessel_owner == "Samir de Navegacion S.A."
    assert tanker.imo == "9182253" and tanker.vessel_flag == "GA" and tanker.aliases == ["SHADOW STAR I"]
    assert company.entity_type == "company" and company.programs == ["UKRAINE-EO13662", "RUSSIA-EO14024", "SDGT"] and company.aliases == ["DARKFLEET"]
    assert person.entity_type == "person"


def test_eu_parser():
    records = eu_sanctions.parse_eu(EU_XML)
    assert len(records) == 2
    company, person = records
    assert company.name == "Dark Fleet Shipping LLC" and company.aliases == ["Darkfleet"]
    assert company.entity_type == "company"  # IMO company number does not make it a vessel
    assert company.imo == "1234567" and company.country == "RU" and company.programs == ["RUS"]
    assert company.designation_date == datetime(2022, 3, 15)
    assert person.entity_type == "person" and person.country == "RU"


def test_un_parser():
    records = un_sanctions.parse_un(UN_XML)
    assert {r.entity_type for r in records} == {"company", "person"}
    company = next(r for r in records if r.entity_type == "company")
    assert company.imo == "1790183" and company.un_committee == "DPRK" and company.aliases == ["OMM"]
    person = next(r for r in records if r.entity_type == "person")
    assert person.name == "IVAN IVANOV" and person.aliases == ["Vanya"] and person.country == "KP"
    assert person.designation_date == datetime(2016, 3, 2)


def test_helpers():
    assert normalize_name("  Gazprom-Neft, PJSC (AO) ") == "GAZPROM NEFT PJSC AO"
    assert extract_imo("Vessel Registration Identification IMO 9182253; Former name X") == "9182253"
    assert extract_imo("no number here") is None


def test_compare_sanctions_lists():
    existing = {
        "1": {"id": 10, "source_id": "1", "name": "OLD NAME", "programs": ["A"], "imo": None, "is_active": True},
        "2": {"id": 11, "source_id": "2", "name": "GONE", "programs": [], "imo": None, "is_active": True},
        "3": {"id": 12, "source_id": "3", "name": "BACK", "programs": [], "imo": None, "is_active": False},
    }
    incoming = [
        SanctionedEntityRecord("OFAC", "1", "New Name", "company", programs=["A", "B"]),
        SanctionedEntityRecord("OFAC", "3", "BACK", "company"),
        SanctionedEntityRecord("OFAC", "4", "Brand New", "vessel", imo="1111111"),
    ]
    changes = compare_sanctions_lists(existing, incoming, "OFAC")
    assert [r.source_id for r in changes.new] == ["4"]
    assert [i for i, _ in changes.relisted] == [12]
    assert changes.changed[0][0] == 10 and set(changes.changed[0][2]) == {"name", "programs"}
    assert [row["id"] for row in changes.delisted] == [11]
    # A truncated download must not mass-delist
    truncated = compare_sanctions_lists(existing, incoming[:1], "OFAC", min_fraction=0.9)
    assert truncated.skipped_delisting and truncated.delisted == []


class Row:
    """Minimal stand-in for a SanctionsEntity ORM row."""

    def __init__(self, **kw):
        defaults = dict(
            designating_authority="OFAC", name_normalized=None, entity_type="vessel", programs=[], aliases=[],
            imo=None, mmsi=None, country_linked=None, vessel_flag=None, designation_date=None,
        )
        self.__dict__.update({**defaults, **kw})


class VesselStub:
    def __init__(self, **kw):
        defaults = dict(mmsi="273123456", imo=None, name="", flag_state="RU", owner_name=None, registered_operator=None, beneficial_owner=None)
        self.__dict__.update({**defaults, **kw})


@pytest.fixture
def index():
    return SanctionsIndex([
        Row(id=1, name="SHADOW STAR", imo="9182253", vessel_flag="GA", programs=["RUSSIA-EO14024"], aliases=["SHADOW STAR I"]),
        Row(id=2, name="DARK FLEET SHIPPING LLC", entity_type="company", country_linked="RU", programs=["RUSSIA-EO14024"], aliases=["DARKFLEET"]),
        Row(id=3, designating_authority="EU", name="Dark Fleet Shipping LLC", entity_type="company", programs=["RUS"]),
        Row(id=4, name="MAR AZUL", vessel_flag="CU", programs=["CUBA"]),
    ])


def test_index_matching(index):
    imo_hit = index.match_vessel(VesselStub(imo="9182253", name="RENAMED", flag_state="GA"))
    assert imo_hit[0].match_type == "imo" and imo_hit[0].confidence == 0.95 and imo_hit[0].severity == "critical"

    exact = index.match_vessel(VesselStub(name="Shadow Star", flag_state="GA"))
    assert exact[0].match_type == "name_exact" and exact[0].confidence == 0.9

    fuzzy = index.match_vessel(VesselStub(name="SHADOW STARR", flag_state="GA"))
    assert fuzzy[0].match_type == "name_fuzzy" and fuzzy[0].confidence == 0.7 and fuzzy[0].similarity > 0.9

    owner = index.match_vessel(VesselStub(name="INNOCENT", owner_name="Dark Fleet Shipping LLC"))
    assert {m.authority for m in owner} == {"OFAC", "EU"}
    assert all(m.breach_type == "owner_match" for m in owner)
    assert max(m.confidence for m in owner) == 0.65  # OFAC row has matching country RU

    flag = index.match_vessel(VesselStub(name="UNKNOWN", flag_state="IR"))
    assert flag[0].match_type == "flag_program" and flag[0].programs == ["IRAN"]

    assert index.match_vessel(VesselStub(name="COMPLETELY CLEAN", flag_state="NL")) == []
    assert index.match_name("darkfleet")[0].entity.id == 2  # alias hit


def test_sanctions_api(client):
    from app.bots.sanctions import sanctions_bot
    from app.database import SessionLocal
    from app.models.sanctions import SanctionsEntity, SanctionsUpdate
    from app.utils.time import utcnow

    with SessionLocal() as db:
        db.add_all([
            SanctionsEntity(designating_authority="OFAC", source_id="9001", name="SHADOW STAR", name_normalized="SHADOW STAR", entity_type="vessel", imo="9182253", vessel_flag="GA", programs=["RUSSIA-EO14024"], aliases=["SHADOW STAR I"], is_active=True),
            SanctionsEntity(designating_authority="OFAC", source_id="9002", name="DARK FLEET SHIPPING LLC", name_normalized="DARK FLEET SHIPPING LLC", entity_type="company", programs=["RUSSIA-EO14024"], aliases=["DARKFLEET"], country_linked="RU", is_active=True),
            SanctionsEntity(designating_authority="EU", source_id="EU.1.1", name="Dark Fleet Shipping LLC", name_normalized="DARK FLEET SHIPPING LLC", entity_type="company", programs=["RUS"], is_active=True),
            SanctionsEntity(designating_authority="UN", source_id="77", name="OLD ENTITY", name_normalized="OLD ENTITY", entity_type="company", is_active=False),
            SanctionsUpdate(timestamp=utcnow(), authority="OFAC", update_type="new_designation", entity_name="SHADOW STAR", entity_type="vessel", new_status={"programs": ["RUSSIA-EO14024"]}),
        ])
        db.commit()
    sanctions_bot.rebuild_index()

    search = client.get("/api/sanctions/entities?query=dark fleet").json()
    assert search["total"] == 2
    assert all(e["designating_authorities"] == ["EU", "OFAC"] for e in search["entities"])
    assert client.get("/api/sanctions/entities?query=9182253").json()["entities"][0]["name"] == "SHADOW STAR"
    assert client.get("/api/sanctions/entities?query=darkfleet&authority=OFAC").json()["total"] == 1
    assert client.get("/api/sanctions/entities?query=old entity").json()["total"] == 0  # inactive hidden by default

    check = client.post("/api/sanctions/check-entity", json={"entity_name": "Dark Fleet Shipping", "requested_by": "analyst"}).json()
    assert check["is_sanctioned"] is True and set(check["designating_authorities"]) == {"EU", "OFAC"}
    assert client.post("/api/sanctions/check-entity", json={"entity_name": "Totally Legit Trading"}).json()["is_sanctioned"] is False

    updates = client.get("/api/sanctions/updates?timeframe=7").json()
    assert updates["total_updates"] == 1 and updates["summary"]["OFAC"]["new_designation"] == 1
    report = client.get("/api/sanctions/report/7days").json()
    assert report["total_updates"] == 1 and report["active_listings"]["OFAC"] >= 2
    assert client.get("/api/sanctions/report/soon").status_code == 422
    assert client.get("/api/sanctions/status").json()["index_size"] >= 3
    assert client.get("/api/sanctions/vessel/000000000").status_code == 404
