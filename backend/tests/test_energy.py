"""Energy flow monitor: cargo estimates, facility geofencing, shipment reconstruction, dark-oil indicators, API."""

from datetime import timedelta

import pytest

from app.analysis.energy import estimate_cargo, facility_by_port, facility_containing, is_tanker, pearson, score_pattern, size_class
from app.bots.energy import EnergyBot
from app.database import SessionLocal
from app.models.energy import DarkOilIndicator, EnergyFacility, EnergyFlowSnapshot, OilTankerShipment
from app.models.maritime import EvasionEvent, PortCallEvent, TransshipmentEvent, Vessel
from app.utils.time import utcnow

MMSI_A, MMSI_B, MMSI_C = "273777001", "636777002", "273777003"


@pytest.fixture(scope="module", autouse=True)
def _cleanup(client):
    yield
    with SessionLocal() as db:
        db.query(DarkOilIndicator).delete()
        db.query(OilTankerShipment).delete()
        db.query(EnergyFlowSnapshot).delete()
        vessels = db.query(Vessel).filter(Vessel.mmsi.in_([MMSI_A, MMSI_B, MMSI_C])).all()
        ids = [v.id for v in vessels]
        if ids:
            db.query(PortCallEvent).filter(PortCallEvent.vessel_id.in_(ids)).delete(synchronize_session=False)
            db.query(EvasionEvent).filter(EvasionEvent.vessel_id.in_(ids)).delete(synchronize_session=False)
            db.query(TransshipmentEvent).filter(TransshipmentEvent.vessel_a_id.in_(ids)).delete(synchronize_session=False)
        # the immutable audit log references these vessels, so park them a year in the past instead of deleting
        for v in vessels:
            v.last_ais_update = utcnow() - timedelta(days=365)
            v.current_position_lat = v.current_position_lon = None
            v.sanctioned_status, v.risk_score = "clear", 0.0
        db.query(EnergyFacility).delete()
        db.commit()


def test_cargo_and_size_rules():
    assert is_tanker("Tanker") and is_tanker("Crude Oil Tanker") and not is_tanker("Cargo") and not is_tanker(None)
    assert size_class(245)[0] == "aframax_lr2" and size_class(330)[0] == "vlcc" and size_class(None) is None
    laden = estimate_cargo(245, 8.0, 14.5, "crude", loading=True)
    assert laden.laden is True and laden.basis == "draught_change" and 650_000 <= laden.barrels <= 800_000
    ballast = estimate_cargo(245, 14.5, 8.0, "crude", loading=True)
    assert ballast.laden is False and ballast.barrels is None
    guess = estimate_cargo(275, None, 16.5, "crude", loading=True)
    assert guess.laden is True and guess.basis == "draught_vs_class_max" and guess.size_class == "suezmax"
    lng = estimate_cargo(290, 9, 12, "lng")
    assert lng.barrels is None and lng.basis == "lng_no_barrel_estimate"
    assert estimate_cargo(None, None, None, "crude").laden is None


def test_facility_geofence_and_scoring():
    hit = facility_containing(60.34, 28.70)
    assert hit and hit[0]["name"].startswith("Primorsk")
    assert facility_containing(0.0, 0.0) is None and facility_containing(None, None) is None
    assert facility_by_port("Kozmino")["type"] == "crude_export" and facility_by_port("Helsinki") is None
    score, severity = score_pattern("ais_gap_after_loading", vessel_sanctioned=True, vessel_risk=0.9)
    assert score == 0.9 and severity == "critical"
    score2, severity2 = score_pattern("sts_hub_loitering", vessel_sanctioned=False, vessel_risk=0.2)
    assert score2 == 0.6 and severity2 == "medium"
    assert pearson([1, 2, 3, 4, 5], [2, 4, 6, 8, 10]) == 1.0 and pearson([1, 1, 1, 1, 1], [1, 2, 3, 4, 5]) is None and pearson([1, 2], [1, 2]) is None


def test_shipments_dark_oil_snapshots_and_api(client):
    bot = EnergyBot()
    synced = bot._sync_facilities()
    assert synced["total"] >= 50 and synced["added"] >= 50 and bot._sync_facilities()["added"] == 0
    now = utcnow()
    with SessionLocal() as db:
        primorsk = db.query(EnergyFacility).filter_by(facility_name="Primorsk crude terminal").one()
        laconian = db.query(EnergyFacility).filter(EnergyFacility.facility_name.like("Laconian%")).one()
        a = Vessel(mmsi=MMSI_A, imo="9700001", name="TEST SHADOW AFRA", flag_state="GA", ship_type="Tanker", length_m=245, draught=14.6, sanctioned_status="flagged", risk_score=0.7,
                   current_position_lat=36.6, current_position_lon=22.7, current_speed=0.3, last_ais_update=now - timedelta(minutes=5))
        b = Vessel(mmsi=MMSI_B, imo="9700002", name="TEST CLEAN VLCC", flag_state="LR", ship_type="Crude Oil Tanker", length_m=330, draught=10.0, sanctioned_status="clear", risk_score=0.1,
                   current_position_lat=36.6, current_position_lon=22.71, current_speed=0.2, last_ais_update=now - timedelta(minutes=5))
        c = Vessel(mmsi=MMSI_C, imo="9700003", name="TEST BALLAST", flag_state="RU", ship_type="Tanker", length_m=180, draught=7.0, sanctioned_status="clear", risk_score=0.2,
                   current_position_lat=59.90, current_position_lon=30.2, current_speed=0.0, last_ais_update=now - timedelta(minutes=5))
        db.add_all([a, b, c])
        db.flush()
        # A loaded at Primorsk (maritime bot port call: laden departure), then an AIS gap and an STS meeting with B
        db.add(PortCallEvent(vessel_id=a.id, mmsi=a.mmsi, port_name="Primorsk", port_code="RUPRI", port_country="RU", is_sanctioned_facility=True, facility_risk_level="high",
                             arrival_time=now - timedelta(days=6), departure_time=now - timedelta(days=5), dwell_time_hours=24, draught_arrival=8.2, draught_departure=14.6, flags_raised=["sanctioned_facility"]))
        # C: ballast departure from Primorsk -> not a shipment
        db.add(PortCallEvent(vessel_id=c.id, mmsi=c.mmsi, port_name="Primorsk", port_code="RUPRI", port_country="RU", is_sanctioned_facility=True, facility_risk_level="high",
                             arrival_time=now - timedelta(days=3), departure_time=now - timedelta(days=2), dwell_time_hours=24, draught_arrival=14.0, draught_departure=7.0, flags_raised=["sanctioned_facility"]))
        db.add(EvasionEvent(vessel_id=a.id, mmsi=a.mmsi, event_type="ais_gap", severity="high", confidence_score=0.8, timestamp=now - timedelta(days=4), details={"gap_hours": 19}, summary="gap"))
        db.add(TransshipmentEvent(vessel_a_id=a.id, vessel_b_id=b.id, vessel_a_mmsi=a.mmsi, vessel_b_mmsi=b.mmsi, timestamp=now - timedelta(days=1), location_lat=36.6, location_lon=22.7, proximity_meters=120, duration_minutes=240, confidence_score=0.8))
        db.commit()
        a_id, b_id, primorsk_id, laconian_id = a.id, b.id, primorsk.id, laconian.id

    visits = bot._track_visits()
    assert visits["linked"] >= 2 and visits["opened"] >= 2  # A and B loitering in the Laconian Gulf STS anchorage
    with SessionLocal() as db:
        calls = db.query(PortCallEvent).filter(PortCallEvent.vessel_id.in_([a_id, b_id]), PortCallEvent.energy_facility_id == laconian_id).all()
        assert len(calls) == 2 and all(c.departure_time is None and c.draught_arrival for c in calls)
        primorsk_call = db.query(PortCallEvent).filter_by(vessel_id=a_id, port_name="Primorsk").one()
        assert primorsk_call.energy_facility_id == primorsk_id
        # backdate the loitering so the STS-hub rule fires
        for call in calls:
            call.arrival_time = now - timedelta(hours=30)
        db.commit()

    built = bot._build_shipments()
    assert built["created"] == 1  # A's laden departure; C's ballast departure is skipped
    with SessionLocal() as db:
        shipment = db.query(OilTankerShipment).filter_by(vessel_id=a_id).one()
        assert shipment.sanctioned_route and shipment.laden is True and shipment.origin_country == "RU" and shipment.loading_facility_id == primorsk_id
        assert 650_000 <= shipment.cargo_volume_barrels <= 800_000 and shipment.evidence["size_class"] == "aframax_lr2"
        assert shipment.status == "transshipped" and shipment.transshipment_suspect and shipment.discharge_facility_id == laconian_id
        assert shipment.dark_oil_suspect  # flagged vessel on a sanctioned route
        shipment_id = shipment.id
    assert bot._build_shipments()["created"] == 0

    dark = bot._detect_dark_oil()
    assert dark["created"] >= 4
    with SessionLocal() as db:
        patterns = {i.detected_pattern: i for i in db.query(DarkOilIndicator).all()}
        assert "sanctioned_vessel_loading" in patterns and "ais_gap_after_loading" in patterns and "sts_transfer" in patterns and "sts_hub_loitering" in patterns
        gap = patterns["ais_gap_after_loading"]
        assert gap.shipment_id == shipment_id and gap.severity == "critical" and gap.suspected_origin == "RU" and "19 h" in gap.summary
        assert patterns["sts_transfer"].evidence["partner_mmsi"] == MMSI_B
    assert bot._detect_dark_oil()["created"] == 0  # idempotent

    snaps = bot._snapshot_flows()
    assert snaps["snapshots"] >= 2
    with SessionLocal() as db:
        primorsk = db.get(EnergyFacility, primorsk_id)
        assert primorsk.tanker_calls_30d == 2 and primorsk.last_activity_at is not None and primorsk.estimated_utilization is not None
        day = (now - timedelta(days=5)).replace(hour=0, minute=0, second=0, microsecond=0)
        snap = db.query(EnergyFlowSnapshot).filter_by(facility_id=primorsk_id, day=day).one()
        assert snap.laden_departures == 1 and snap.tanker_departures == 1 and snap.estimated_barrels > 600_000
        laconian = db.get(EnergyFacility, laconian_id)
        assert laconian.tanker_calls_7d == 2

    # --- API
    facilities = client.get("/api/energy/facilities?sanctioned=true").json()
    assert any(f["facility_name"].startswith("Kharg") for f in facilities) and all(f["is_sanctioned_facility"] for f in facilities)
    geo = client.get("/api/energy/facilities/geojson").json()
    assert geo["type"] == "FeatureCollection" and len(geo["features"]) >= 50
    detail = client.get(f"/api/energy/facilities/{primorsk_id}").json()
    assert detail["facility"]["id"] == primorsk_id and len(detail["recent_calls"]) == 2 and detail["shipments"][0]["vessel_name"] == "TEST SHADOW AFRA" and detail["flows"]
    assert client.get("/api/energy/facilities/999999").status_code == 404
    shipments = client.get("/api/energy/shipments?sanctioned_only=true&dark_oil_only=true").json()
    assert shipments["total"] == 1 and shipments["shipments"][0]["loading_date"].endswith("Z")
    dark_oil = client.get("/api/energy/dark-oil?min_confidence=0.8").json()
    assert dark_oil["total"] >= 2 and dark_oil["indicators"][0]["confidence_score"] >= 0.8
    updated = client.post(f"/api/energy/dark-oil/{dark_oil['indicators'][0]['id']}/status?status=investigating&analyst=alex").json()
    assert updated["investigation_status"] == "investigating"
    flows = client.get("/api/energy/flows?days=30&sanctioned_only=true").json()
    assert len(flows["points"]) >= 1
    context = client.get("/api/energy/price-context?days=30").json()
    assert "series" in context and context["days"] == 30
    summary = client.get("/api/energy/summary?days=7").json()
    assert summary["sanctioned_shipments"] == 1 and summary["dark_oil_indicators"]["sts_transfer"] == 1 and summary["by_origin"] == {"RU": 1}
    assert client.get("/api/energy/status").status_code == 200
