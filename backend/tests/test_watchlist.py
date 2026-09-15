"""Analyst watchlists: items, hits, alerts, lookup."""

import pytest

from app.bots.watchlist import WatchlistBot
from app.database import SessionLocal
from app.models.maritime import EvasionEvent, Vessel
from app.models.sanctions import SanctionsEntity, SanctionsUpdate
from app.models.tier2 import LegalEvent
from app.models.watchlist import WatchlistHit, WatchlistItem
from app.utils.time import utcnow


@pytest.fixture(scope="module", autouse=True)
def _cleanup(client):
    yield
    with SessionLocal() as db:
        db.query(WatchlistHit).delete()
        db.query(WatchlistItem).delete()
        db.query(LegalEvent).filter(LegalEvent.source_id.like("wl-%")).delete(synchronize_session=False)
        db.query(SanctionsUpdate).filter(SanctionsUpdate.entity_name == "WATCHED PARTY LLC").delete(synchronize_session=False)
        db.query(SanctionsEntity).filter(SanctionsEntity.source_id == "wl-1").delete(synchronize_session=False)
        vessel = db.query(Vessel).filter_by(mmsi="273777888").first()
        if vessel:
            db.query(EvasionEvent).filter_by(vessel_id=vessel.id).delete()
            db.delete(vessel)
        db.commit()


def test_watchlist_items_and_hits(client, monkeypatch):
    sent = []
    from app import notifications

    monkeypatch.setattr(notifications, "send_alert", lambda kind, title, text, severity="high", data=None: sent.append((kind, title, severity)))
    from app.bots.runtime import bot_loop

    monkeypatch.setattr(bot_loop, "submit", lambda coro: coro.close())  # run the passes synchronously below instead of on the bot loop
    with SessionLocal() as db:
        vessel = Vessel(mmsi="273777888", imo="9700888", name="WATCHED STAR", flag_state="GA", ship_type="Tanker")
        db.add(vessel)
        entity = SanctionsEntity(designating_authority="OFAC", source_id="wl-1", name="WATCHED PARTY LLC", name_normalized="WATCHED PARTY LLC", entity_type="company", programs=["IRAN"], is_active=True, first_seen_at=utcnow(), last_updated=utcnow())
        db.add(entity)
        db.flush()
        db.add(EvasionEvent(vessel_id=vessel.id, mmsi=vessel.mmsi, event_type="ais_gap", severity="medium", confidence_score=0.5, timestamp=utcnow(), summary="AIS silent for 9 h", created_at=utcnow()))
        db.add(LegalEvent(source="doj", source_id="wl-legal", title="Watched Party LLC charged with sanctions evasion", matched_entity_id=entity.id, event_type="indictment", event_date=utcnow(), discovered_at=utcnow()))
        db.commit()
        entity_id = entity.id

    # vessel by name resolves to its MMSI; the first pass collects context without alerting
    created = client.post("/api/watchlist", json={"kind": "vessel", "key": "WATCHED STAR", "note": "shadow fleet suspect"})
    assert created.status_code == 201 and created.json()["key"] == "273777888" and created.json()["label"] == "WATCHED STAR (GA)"
    item_id = created.json()["id"]
    assert client.post("/api/watchlist", json={"kind": "vessel", "key": "WATCHED STAR"}).json()["id"] == item_id  # idempotent
    party = client.post("/api/watchlist", json={"kind": "entity", "key": str(entity_id)}).json()
    keyword = client.post("/api/watchlist", json={"kind": "keyword", "key": "Watched Party"}).json()
    assert client.post("/api/watchlist", json={"kind": "vessel", "key": "NO SUCH SHIP 42"}).status_code == 404
    result = WatchlistBot.check_sync()
    assert result["items"] >= 3 and result["hits"] >= 3 and sent == []  # first pass: context only
    hits = client.get(f"/api/watchlist/hits?item_id={item_id}").json()
    assert hits and hits[0]["record_type"] == "evasion_event" and hits[0]["item_label"] == "WATCHED STAR (GA)"
    party_hits = {h["record_type"] for h in client.get(f"/api/watchlist/hits?item_id={party['id']}").json()}
    assert "legal_event" in party_hits
    assert any(h["record_type"] == "legal_event" for h in client.get(f"/api/watchlist/hits?item_id={keyword['id']}").json())

    # a new record after the first pass -> stored once and alerted
    with SessionLocal() as db:
        db.add(SanctionsUpdate(timestamp=utcnow(), authority="EU", update_type="new_designation", entity_id=entity_id, entity_name="WATCHED PARTY LLC"))
        db.commit()
    result = WatchlistBot.check_sync()
    assert result["hits"] >= 1 and sent and sent[0][0] == "watchlist" and "WATCHED PARTY" in sent[0][1]
    assert WatchlistBot.check_sync()["hits"] == 0

    listing = client.get("/api/watchlist").json()
    assert {i["kind"] for i in listing} >= {"vessel", "entity", "keyword"} and all(i["hit_count"] >= 1 for i in listing if i["id"] in (item_id, party["id"]))
    assert client.get("/api/watchlist/lookup?kind=vessel&key=273777888").json()["watched"] is True
    assert client.get("/api/watchlist/lookup?kind=wallet&key=nothing").json()["watched"] is False
    assert client.patch(f"/api/watchlist/{item_id}", json={"alert": False, "note": "paused alerts"}).json()["alert"] is False
    summary = client.get("/api/watchlist/summary").json()
    assert summary["items"] >= 3 and summary["hits"] >= 3
    assert client.delete(f"/api/watchlist/{item_id}").status_code == 204
    assert client.get("/api/watchlist/lookup?kind=vessel&key=273777888").json()["watched"] is False
    assert client.get("/api/maritime/audit-log?action_type=watchlist_removed").json()["total"] >= 1
