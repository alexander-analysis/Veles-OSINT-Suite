"""Phase 4: reports, exports, optional API token, notifications."""

import asyncio

from app import notifications
from app.config import settings
from app.reports.pdf import Report, Section, build_pdf


def test_pdf_builder_renders_sections():
    pdf = build_pdf(Report(title="T", subtitle="S", classification="CONFIDENTIAL", sections=[Section("A", text="x & y <z>", items=[("k", 1.5)]), Section("B", table=[["h1", "h2"], [1, None]], page_break_before=True)]))
    assert pdf[:5] == b"%PDF-" and len(pdf) > 1500


def test_market_export_formats(client):
    assert client.get("/api/market/export/24h").json()["summary"]["alerts"] >= 0
    assert client.get("/api/market/export/7d?format=pdf&classification=SECRET").content[:5] == b"%PDF-"
    csv_export = client.get("/api/market/export/7d?format=csv")
    assert csv_export.headers["content-type"].startswith("text/csv") and csv_export.text.startswith("timestamp,asset")
    assert client.get("/api/market/export/soon").status_code == 422


def test_sanctions_report_pdf(client):
    response = client.get("/api/sanctions/report/7days?format=pdf")
    assert response.status_code == 200 and response.content[:5] == b"%PDF-"


def test_api_token_protection(client, monkeypatch):
    monkeypatch.setattr(settings, "VELES_API_TOKEN", "s3cret")
    assert client.get("/api/health").status_code == 200  # always public
    assert client.get("/api/market/prices").status_code == 401
    assert client.get("/api/market/prices", headers={"X-API-Key": "wrong"}).status_code == 401
    assert client.get("/api/market/prices", headers={"X-API-Key": "s3cret"}).status_code == 200
    assert client.get("/api/market/prices", headers={"Authorization": "Bearer s3cret"}).status_code == 200
    assert client.get("/api/health").json()["bots"]["auth"]["token_required"] is True
    with client.websocket_connect("/api/maritime/stream?access_token=s3cret") as ws:
        assert ws.receive_json()["type"] == "hello"
    monkeypatch.setattr(settings, "VELES_API_TOKEN", "")
    assert client.get("/api/market/prices").status_code == 200


def test_notifications_disabled_is_noop_and_digest_builds(client):
    notifications.send_alert("breach", "t", "x", "critical")  # disabled in settings.yaml -> no exception, no channels
    assert notifications.enabled_channels() == {"webhook": False, "email": False}
    assert asyncio.run(notifications.deliver("subject", "body")) == {}
    subject, body = notifications.build_daily_digest()
    assert subject.startswith("[VELES] Daily intelligence digest") and "Maritime:" in body
