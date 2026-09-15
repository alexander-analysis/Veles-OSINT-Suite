"""Maritime analysis units and an end-to-end ingest -> screen -> detect -> API flow (no network)."""

from datetime import timedelta

import pytest

from app.analysis import evasion, ports as port_rules, transshipment as sts
from app.analysis.geospatial import describe_location, haversine_m, lanes_containing, nearest_port, zones_containing
from app.integrations.ais_common import AISPosition, flag_from_mmsi, ship_type_name
from app.utils.time import utcnow

PRIMORSK = (60.336, 28.700)
OPEN_SEA = (59.95, 25.30)  # Gulf of Finland, away from ports


def test_geospatial_helpers():
    assert 5_000 < haversine_m(60.0, 25.0, 60.045, 25.0) < 5_100
    assert nearest_port(*PRIMORSK)[0]["name"] == "Primorsk"
    assert nearest_port(*OPEN_SEA, within_km=3) is None
    assert {z.name for z in zones_containing(*PRIMORSK)} == {"Gulf of Finland - Russian terminals"}
    assert any(lane.name == "Gulf of Finland corridor" for lane in lanes_containing(*OPEN_SEA))
    assert "Primorsk" in describe_location(60.30, 28.60)
    assert flag_from_mmsi("273123456") == "RU" and flag_from_mmsi("999000000") == "XX"
    assert ship_type_name(84) == "Tanker" and ship_type_name(52) == "Tug"


def test_ais_position_normalisation():
    p = AISPosition(mmsi=273000001, lat=60.0, lon=25.0, timestamp=utcnow(), source="test", heading=511, speed=102.3, imo="0")
    assert p.mmsi == "273000001" and p.heading is None and p.speed is None and p.imo is None and p.flag == "RU"


def test_ais_gap_severity():
    now = utcnow()
    at_sea = AISPosition(mmsi="1", lat=OPEN_SEA[0], lon=OPEN_SEA[1], timestamp=now, source="test")
    assert evasion.detect_ais_gap(now - timedelta(hours=2), 10.0, 59.9, 25.0, at_sea, threshold_hours=6) is None
    gap = evasion.detect_ais_gap(now - timedelta(hours=8), 10.0, 59.9, 25.0, at_sea, threshold_hours=6)
    assert gap.event_type == "ais_gap" and gap.severity == "medium" and gap.details["gap_hours"] == 8.0
    moored = evasion.detect_ais_gap(now - timedelta(hours=8), 0.0, 59.9, 25.0, at_sea, threshold_hours=6)
    assert moored.severity == "low"
    in_zone = AISPosition(mmsi="1", lat=PRIMORSK[0], lon=PRIMORSK[1], timestamp=now, source="test")
    zone_gap = evasion.detect_ais_gap(now - timedelta(hours=30), 10.0, 59.9, 25.0, in_zone, threshold_hours=6)
    assert zone_gap.severity == "critical" and "Gulf of Finland" in zone_gap.summary


class VesselStub:
    _ids = iter(range(1, 10_000))

    def __init__(self, **kw):
        defaults = dict(id=next(self._ids), mmsi="273000000", imo=None, name="STUB", flag_state="RU", ship_type="Tanker", current_position_lat=None, current_position_lon=None,
                        current_speed=0.0, sanctioned_status="clear", risk_score=0.0, last_ais_update=utcnow(), owner_name=None, registered_operator=None, beneficial_owner=None)
        self.__dict__.update({**defaults, **kw})


def test_identity_changes_and_conflict():
    vessel = VesselStub(name="OLD NAME", flag_state="RU")
    report = AISPosition(mmsi="273000000", lat=60.0, lon=25.0, timestamp=utcnow(), source="test", name="NEW NAME", flag="GA")
    events = {e.event_type: e for e in evasion.detect_identity_changes(vessel, report)}
    assert set(events) == {"name_change", "flag_change"} and events["flag_change"].severity == "high"
    conflict = evasion.identity_conflict(VesselStub(mmsi="273000009", name="ORIGINAL", flag_state="RU"), AISPosition(mmsi="620000001", imo="9182253", lat=60, lon=25, timestamp=utcnow(), source="test", name="RENAMED"))
    assert conflict.event_type == "identity_conflict" and conflict.severity == "high" and conflict.details["previous_mmsi"] == "273000009"


def test_transshipment_pairs_duration_and_assessment():
    a = VesselStub(mmsi="A", current_position_lat=OPEN_SEA[0], current_position_lon=OPEN_SEA[1], current_speed=0.2, ship_type="Tanker")
    b = VesselStub(mmsi="B", current_position_lat=OPEN_SEA[0] + 0.002, current_position_lon=OPEN_SEA[1], current_speed=0.4, ship_type="Cargo")
    fast = VesselStub(mmsi="C", current_position_lat=OPEN_SEA[0], current_position_lon=OPEN_SEA[1] + 0.001, current_speed=9.0)
    tug = VesselStub(mmsi="D", current_position_lat=OPEN_SEA[0], current_position_lon=OPEN_SEA[1] + 0.001, current_speed=0.1, ship_type="Tug")
    in_port_a = VesselStub(mmsi="E", current_position_lat=PRIMORSK[0], current_position_lon=PRIMORSK[1], current_speed=0.0)
    in_port_b = VesselStub(mmsi="F", current_position_lat=PRIMORSK[0] + 0.001, current_position_lon=PRIMORSK[1], current_speed=0.0)
    pairs = sts.find_proximity_pairs([a, b, fast, tug, in_port_a, in_port_b], proximity_meters=500)
    assert [(p[0].mmsi, p[1].mmsi) for p in pairs] == [("A", "B")]

    class Fix:
        def __init__(self, minutes_ago, lat, lon):
            self.timestamp, self.latitude, self.longitude = utcnow() - timedelta(minutes=minutes_ago), lat, lon

    history_a = [Fix(m, OPEN_SEA[0], OPEN_SEA[1]) for m in (90, 60, 30, 0)]
    history_b = [Fix(m, OPEN_SEA[0] + 0.002, OPEN_SEA[1]) for m in (88, 58, 28, 1)]
    duration, started = sts.proximity_duration(history_a, history_b, 500, timedelta(hours=8))
    assert duration == 90 and started is not None
    candidate = sts.assess_candidate(a, b, 220, duration, started, 30, utcnow())
    assert candidate is not None and candidate.confidence >= 0.55 and "within 220 m for 90 min" in candidate.summary
    assert sts.assess_candidate(a, b, 220, 10, started, 30, utcnow()) is None


def test_port_rules():
    vessel = VesselStub(current_position_lat=PRIMORSK[0], current_position_lon=PRIMORSK[1], current_speed=0.2, flag_state="GA")
    state = port_rules.port_for_vessel(vessel)
    assert state.port["name"] == "Primorsk" and port_rules.is_arrival(vessel, state)
    flags = port_rules.port_flags(state.port, 80, 72, vessel)
    assert {"sanctioned_facility", "high_risk_port", "unusual_dwell_time", "flag_of_convenience_at_high_risk_port"} <= set(flags)
    assert port_rules.predicted_cargo(vessel, state.port) == "crude/products"


# --------------------------------------------------------------- end to end
@pytest.fixture(scope="module")
def maritime_setup(client):
    """Seed a small sanctions index and reset the maritime bot state."""
    from app.bots.maritime import maritime_bot
    from app.bots.sanctions import sanctions_bot
    from app.database import SessionLocal
    from app.models.sanctions import SanctionsEntity

    with SessionLocal() as db:
        db.add_all([
            SanctionsEntity(designating_authority="OFAC", source_id="mt-1", name="SHADOW STAR", name_normalized="SHADOW STAR", entity_type="vessel", imo="9182253", vessel_flag="GA", programs=["RUSSIA-EO14024"], is_active=True),
            SanctionsEntity(designating_authority="OFAC", source_id="mt-2", name="VICTORIA", name_normalized="VICTORIA", entity_type="vessel", imo="1111111", vessel_flag="IR", programs=["SDGT"], is_active=True),
        ])
        db.commit()
    sanctions_bot.rebuild_index()
    maritime_bot.touched.clear()
    return maritime_bot


def _pos(mmsi, lat, lon, minutes_ago=0, **kw):
    return AISPosition(mmsi=mmsi, lat=lat, lon=lon, timestamp=utcnow() - timedelta(minutes=minutes_ago), source="test", **kw)


def test_ingest_screens_and_detects(client, maritime_setup):
    bot = maritime_setup
    cfg = bot.config()
    # batch 1 (90 min ago): the designated hull (renamed), two loitering tankers, a namesake, a soon-to-be-renamed vessel
    batch1 = [
        _pos("620000001", *PRIMORSK, 90, name="STAR OF THE SEA", imo="9182253", flag="GA", speed=0.0, ship_type="Tanker"),
        _pos("273000101", *OPEN_SEA, 90, name="TANKER ONE", speed=0.3, ship_type="Tanker", imo="9000001"),
        _pos("273000102", OPEN_SEA[0] + 0.002, OPEN_SEA[1], 90, name="TANKER TWO", speed=0.5, ship_type="Tanker", imo="9000002"),
        _pos("230000201", 60.15, 24.95, 90, name="VICTORIA", imo="9000003", flag="FI", speed=0.0),
        _pos("273000301", 59.80, 26.00, 600, name="OLD NAME", flag="RU", speed=12.0, ship_type="Cargo"),
    ]
    stats = bot._ingest(batch1, cfg)
    assert stats["new_vessels"] == 5 and stats["positions"] == 5
    assert stats["breaches"] == 1  # IMO match only - the Finnish VICTORIA has a different IMO (namesake)
    assert stats.get("lane_events", 0) >= 1  # designated vessel inside the Russian-terminal zone

    # later batches: loitering continues; OLD NAME reappears renamed, re-flagged, after a 10 h gap
    for minutes in (60, 30, 0):
        batch = [
            _pos("273000101", *OPEN_SEA, minutes, name="TANKER ONE", speed=0.2, ship_type="Tanker"),
            _pos("273000102", OPEN_SEA[0] + 0.002, OPEN_SEA[1], minutes, name="TANKER TWO", speed=0.4, ship_type="Tanker"),
            _pos("620000001", *PRIMORSK, minutes, name="STAR OF THE SEA", imo="9182253", flag="GA", speed=0.0),
        ]
        if minutes == 0:
            batch.append(_pos("273000301", 60.30, 28.60, 0, name="NEW NAME", flag="GA", speed=8.0, ship_type="Cargo"))
        stats = bot._ingest(batch, cfg)
    assert stats["name_change"] == 1 and stats["flag_change"] == 1 and stats["ais_gaps"] == 1

    import asyncio

    assert asyncio.run(bot.check_sanctions()) == 0  # nothing new on re-screen
    assert asyncio.run(bot.detect_transshipments()) == 1
    assert asyncio.run(bot.detect_port_calls())["opened"] >= 1
    assert asyncio.run(bot.update_risk_scores()) >= 5


def test_maritime_api(client, maritime_setup):
    geo = client.get("/api/maritime/vessels?bbox=20,58,32,62").json()
    assert geo["vessel_count"] >= 5 and geo["breach_count"] == 1
    designated = next(f for f in geo["features"] if f["properties"]["mmsi"] == "620000001")
    assert designated["properties"]["sanctioned_status"] == "breach_ofac" and designated["properties"]["marker_color"] == "#e74c3c"
    assert client.get("/api/maritime/vessels?risk_filter=breach").json()["vessel_count"] == 1

    table = client.get("/api/maritime/vessels/table?status=breach").json()
    assert table["total"] == 1 and table["vessels"][0]["imo"] == "9182253"
    assert client.get("/api/maritime/vessels/table?q=tanker").json()["total"] == 2

    profile = client.get("/api/maritime/vessel/620000001").json()
    assert profile["vessel"]["risk_score"] >= 0.95
    assert profile["sanctions_matches"][0]["sanctioned_entity"] == "SHADOW STAR" and profile["sanctions_matches"][0]["match_confidence"] == 0.95
    assert len(profile["position_timeline"]) == 4 and profile["position_timeline"][0]["timestamp"].endswith("Z")
    assert profile["port_history"][0]["port_name"] == "Primorsk" and "sanctioned_facility" in profile["port_history"][0]["flags_raised"]
    assert any(a["action_type"] == "breach_detected" for a in profile["audit_history"])
    assert client.get("/api/maritime/vessel/000").status_code == 404

    breaches = client.get("/api/maritime/breaches?authority=OFAC").json()
    assert breaches["total"] == 1 and breaches["breaches"][0]["breach_type"] == "direct_match"
    assert client.get("/api/maritime/breaches/EU").json()["total"] == 0
    assert client.get("/api/maritime/breaches/XX").status_code == 404

    evasion_events = client.get("/api/maritime/evasion-patterns?hours=48").json()
    assert {"name_change", "flag_change", "ais_gap"} <= set(evasion_events["by_type"])
    renamed = next(e for e in evasion_events["events"] if e["event_type"] == "name_change")
    assert renamed["details"] == {"old_name": "OLD NAME", "new_name": "NEW NAME"} and renamed["vessel_name"] == "NEW NAME"

    sts_events = client.get("/api/maritime/transshipment").json()
    assert sts_events["total"] == 1
    event = sts_events["events"][0]
    assert {event["vessel_a"]["name"], event["vessel_b"]["name"]} == {"TANKER ONE", "TANKER TWO"} and event["duration_minutes"] >= 60
    patched = client.patch(f"/api/maritime/transshipment/{event['id']}", json={"investigation_status": "confirmed", "analyst_notes": "verified"})
    assert patched.status_code == 200 and patched.json()["investigation_status"] == "confirmed"

    calls = client.get("/api/maritime/port-calls?only_flagged=true").json()
    assert any(c["port_name"] == "Primorsk" and c["is_sanctioned_facility"] for c in calls["calls"])
    assert client.get("/api/maritime/port-calls/7d").json()["total"] >= 1

    lanes = client.get("/api/maritime/shipping-lanes/violations").json()
    assert lanes["total"] >= 1 and "Gulf of Finland - Russian terminals" in lanes["by_lane"]
    assert client.get("/api/maritime/shipping-lanes").json()["lanes"]["type"] == "FeatureCollection"
    zones = client.get("/api/maritime/sanctions-zones").json()
    assert {"ofac", "eu", "un", "all"} <= set(zones) and zones["all"]["features"]
    assert client.get("/api/maritime/ports").json()["features"]

    linked = client.get("/api/maritime/vessel-correlation/273000101").json()
    assert linked["linked"][0]["mmsi"] == "273000102" and linked["linked"][0]["reasons"][0]["type"] == "transshipment_partner"

    log = client.get("/api/maritime/audit-log?action_type=breach_detected,transshipment_detected").json()
    assert log["total"] >= 2 and log["entries"][0]["is_final"] is True
    assert "breach_detected" in client.get("/api/maritime/audit-log/actions").json()
    csv_export = client.post("/api/maritime/audit-log/export", json={"format": "csv"})
    assert csv_export.status_code == 200 and csv_export.headers["content-type"].startswith("text/csv") and "breach_detected" in csv_export.text
    json_export = client.post("/api/maritime/audit-log/export", json={"format": "json", "classification": "CONFIDENTIAL"}).json()
    assert json_export["classification"] == "CONFIDENTIAL" and json_export["total"] >= 1
    pdf_export = client.post("/api/maritime/audit-log/export", json={"format": "pdf", "classification": "SECRET"})
    assert pdf_export.status_code == 200 and pdf_export.headers["content-type"] == "application/pdf" and pdf_export.content[:5] == b"%PDF-"
    report = client.get("/api/maritime/report?days=7").json()
    assert report["executive_summary"]["breaches"] >= 1 and report["recommendations"]
    assert client.get("/api/maritime/report?days=7&format=pdf&sections=executive_summary,breach_analysis").content[:5] == b"%PDF-"

    # clearing the only breach clears the vessel and is audited
    breach_id = breaches["breaches"][0]["id"]
    cleared = client.patch(f"/api/maritime/breach/{breach_id}", json={"investigation_status": "cleared", "analyst_notes": "false positive", "updated_by": "analyst"})
    assert cleared.status_code == 200 and cleared.json()["investigation_status"] == "cleared"
    assert client.get("/api/maritime/vessels/table?q=620000001").json()["vessels"][0]["sanctioned_status"] == "clear"
    assert client.get("/api/maritime/audit-log?action_type=cleared&user=analyst").json()["total"] == 1
    assert client.get("/api/maritime/status").json()["vessels_tracked"] >= 5


def test_position_anomaly_detection():
    now = utcnow()
    inland = AISPosition(mmsi="273219650", lat=57.64, lon=32.48, timestamp=now, source="test", speed=42.2, ship_type="Other")
    anomaly = evasion.detect_position_anomaly(None, None, None, inland, "Other")
    assert anomaly.event_type == "position_anomaly" and "42.2 kn" in anomaly.summary
    jump = evasion.detect_position_anomaly(now - timedelta(minutes=30), 60.0, 25.0, inland, "Other")
    assert jump.severity == "high" and jump.details["implied_speed_kn"] > 200 and len(jump.details["reasons"]) == 2
    ferry = AISPosition(mmsi="1", lat=60.0, lon=25.0, timestamp=now, source="test", speed=38.0, ship_type="High-speed craft")
    assert evasion.detect_position_anomaly(now - timedelta(minutes=30), 59.9, 24.8, ferry, "High-speed craft") is None
    assert evasion.plausible_max_speed("Tanker") == 30.0


def test_websocket_stream(client):
    with client.websocket_connect("/api/maritime/stream") as ws:
        hello = ws.receive_json()
        assert hello["type"] == "hello" and hello["data"]["clients"] == 1


def test_imo_reconciliation_clears_namesake(client, maritime_setup):
    """A name-only match is auto-cleared once the vessel's own IMO turns out to differ from the listed one."""
    bot = maritime_setup
    cfg = bot.config()
    stats = bot._ingest([_pos("626000777", 5.5, -1.0, 5, name="SHADOW STAR", flag="GA", speed=8.0, ship_type="Tanker")], cfg)
    assert stats["breaches"] == 1  # exact name, flag agrees -> 0.9
    assert client.get("/api/maritime/vessels/table?q=626000777").json()["vessels"][0]["sanctioned_status"] == "breach_ofac"
    stats = bot._ingest([_pos("626000777", 5.6, -1.1, 0, name="SHADOW STAR", flag="GA", speed=8.0, ship_type="Tanker", imo="2222222")], cfg)
    assert stats["breaches_auto_cleared"] == 1
    vessel = client.get("/api/maritime/vessels/table?q=626000777").json()["vessels"][0]
    assert vessel["sanctioned_status"] == "clear" and vessel["imo"] == "2222222"
    cleared = client.get("/api/maritime/audit-log?action_type=cleared&user=system").json()
    assert cleared["total"] >= 1 and "namesake" in cleared["entries"][0]["rationale"]


def test_imo_claims_never_violate_uniqueness(client, maritime_setup):
    """Two live MMSIs claiming one IMO in a batch -> one holder, one identity_conflict; a silent holder transfers."""
    bot = maritime_setup
    cfg = bot.config()
    stats = bot._ingest([
        _pos("636099001", 10.0, 10.0, 1, name="HOLDER", imo="9555555", speed=5.0),
        _pos("636099002", 10.1, 10.1, 0, name="CLAIMANT", imo="9555555", speed=5.0),
    ], cfg)
    assert stats["new_vessels"] == 2 and stats["identity_conflicts"] == 1
    table = {v["mmsi"]: v for v in client.get("/api/maritime/vessels/table?q=6360990").json()["vessels"]}
    assert table["636099001"]["imo"] == "9555555" and table["636099002"]["imo"] is None
    # the holder goes silent for two days; a new MMSI reports the hull -> identity transfers with history
    from app.database import SessionLocal
    from app.models.maritime import Vessel
    with SessionLocal() as db:
        holder = db.execute(__import__("sqlalchemy").select(Vessel).where(Vessel.mmsi == "636099001")).scalar_one()
        holder.last_ais_update = utcnow() - timedelta(days=2)
        db.commit()
    stats = bot._ingest([_pos("636099003", 10.2, 10.2, 0, name="REBORN", imo="9555555", speed=5.0)], cfg)
    assert stats["identity_transfers"] == 1
    table = {v["mmsi"]: v for v in client.get("/api/maritime/vessels/table?q=6360990&max_age_hours=100").json()["vessels"]}
    assert table["636099003"]["imo"] == "9555555" and table["636099001"]["imo"] is None
    profile = client.get("/api/maritime/vessel/636099003").json()
    assert "HOLDER" in profile["vessel"]["historical_names"]
