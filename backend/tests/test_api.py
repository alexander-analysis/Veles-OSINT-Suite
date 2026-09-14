"""Phase 1 smoke tests: schema, health, stub endpoints, config, audit immutability."""

import pytest
from sqlalchemy import inspect, update
from sqlalchemy.exc import DBAPIError

EXPECTED_TABLES = {
    "market_candles",
    "market_alerts",
    "coordination_events",
    "liquidation_cascades",
    "vessels",
    "vessel_positions",
    "sanctions_entities",
    "sanctions_breaches",
    "transshipment_events",
    "port_call_events",
    "shipping_lane_violations",
    "audit_logs",
    "data_retention_policies",
    "alembic_version",
}


def test_schema_created_by_migrations(client):
    from app.database import engine

    assert EXPECTED_TABLES <= set(inspect(engine).get_table_names())


def test_health(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["database"]["ok"] is True
    assert body["scheduler"]["enabled"] is False
    assert body["timestamp"].endswith("Z")
    assert body["last_market_update"] is None


def test_openapi_docs_available(client):
    assert client.get("/docs").status_code == 200
    paths = client.get("/openapi.json").json()["paths"]
    assert {"/api/health", "/api/market/prices", "/api/maritime/vessels", "/api/admin/config"} <= set(paths)


def test_market_prices_stub(client):
    response = client.get("/api/market/prices?assets=BTC,ETH&exchanges=binance")
    assert response.status_code == 200
    body = response.json()
    assert body["data"] == []
    assert body["timestamp"].endswith("Z")


def test_maritime_vessels_geojson(client):
    response = client.get("/api/maritime/vessels?bbox=-180,-90,180,90&risk_filter=all")
    assert response.status_code == 200
    body = response.json()
    assert body["type"] == "FeatureCollection"
    assert body["vessel_count"] == 0
    assert body["features"] == []


def test_maritime_vessels_rejects_bad_bbox(client):
    assert client.get("/api/maritime/vessels?bbox=1,2,3").status_code == 422
    assert client.get("/api/maritime/vessels?bbox=10,0,-10,0").status_code == 422
    assert client.get("/api/maritime/vessels?risk_filter=bogus").status_code == 422


def test_admin_config_roundtrip(client):
    defaults = client.get("/api/admin/config").json()
    assert defaults["market"]["price_anomaly_sigma"] == 3.0

    response = client.post("/api/admin/config", json={"market": {"price_anomaly_sigma": 2.5}})
    assert response.status_code == 200
    assert response.json()["market"]["price_anomaly_sigma"] == 2.5
    # other keys in the section survive a partial patch
    assert response.json()["market"]["assets"] == defaults["market"]["assets"]

    assert client.get("/api/admin/config").json()["market"]["price_anomaly_sigma"] == 2.5

    assert client.post("/api/admin/config", json={"bogus": {"x": 1}}).status_code == 422
    assert client.post("/api/admin/config", json={}).status_code == 422


def test_config_update_is_audited(client):
    from app.database import SessionLocal
    from app.models.audit import AuditLog

    with SessionLocal() as db:
        entries = db.query(AuditLog).filter_by(action_type="config_updated").all()
    assert entries, "config change should be written to the audit log"
    assert entries[-1].supporting_data["patch"] == {"market": {"price_anomaly_sigma": 2.5}}


def test_audit_log_is_immutable(client):
    from app.database import SessionLocal
    from app.models.audit import AuditLog, ImmutableRecordError

    with SessionLocal() as db:
        entry = AuditLog(action_type="test", user_id="pytest", rationale="original")
        db.add(entry)
        db.commit()
        entry_id = entry.id

        # ORM-level guard
        entry.rationale = "tampered"
        with pytest.raises(ImmutableRecordError):
            db.commit()
        db.rollback()

        with pytest.raises(ImmutableRecordError):
            db.delete(entry)
            db.commit()
        db.rollback()

        # Database-level guard (bulk statements bypass ORM events)
        with pytest.raises(DBAPIError):
            db.execute(update(AuditLog).where(AuditLog.id == entry_id).values(rationale="tampered"))
            db.commit()
        db.rollback()

        db.expire_all()
        assert db.get(AuditLog, entry_id).rationale == "original"
