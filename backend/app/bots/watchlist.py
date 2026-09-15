"""Analyst watchlists: every few minutes, look for new records that touch a watched vessel, listed party, company,
wallet, aircraft, domain or keyword, store them as hits and (optionally) fire an instant alert.

Kinds and what counts as a hit:

* ``vessel`` (key = MMSI): evasion indicators, sanctions matches, port calls, STS rendezvous, port state control,
  oil shipments, dark-oil indicators
* ``entity`` (key = sanctions entity id): breaches naming it, legal events, list updates, transfers on its wallets,
  sightings of its aircraft
* ``company`` (key = LEI or name): legal events and breach / ransomware postings naming it
* ``wallet`` (key = address): transfers in or out
* ``aircraft`` (key = registration): ADS-B sightings
* ``domain`` (key = hostname): breach postings and legal events naming it
* ``keyword`` (key = free text): geopolitical events, narratives, legal events, breach postings, PSC records,
  list updates whose title / name contains it
"""

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.blockchain import BlockchainTransaction, BlockchainWallet
from app.models.energy import DarkOilIndicator, OilTankerShipment
from app.models.geopolitical import GeopoliticalEvent
from app.models.maritime import EvasionEvent, PortCallEvent, SanctionsBreach, TransshipmentEvent, Vessel
from app.models.sanctions import SanctionsEntity, SanctionsUpdate
from app.models.tier2 import Aircraft, AircraftSighting, BreachEvent, LegalEvent, Narrative, PscEvent
from app.models.watchlist import WatchlistHit, WatchlistItem
from app.utils import config_store
from app.utils.logger import logger
from app.utils.time import utcnow

log = logger.bind(component="watchlist")

KINDS = ("vessel", "entity", "company", "wallet", "aircraft", "domain", "keyword")
FIRST_LOOKBACK = timedelta(days=7)  # a freshly added item immediately shows the last week


@dataclass
class Hit:
    record_type: str
    record_id: int
    timestamp: datetime
    summary: str
    severity: str = "medium"
    href: str | None = None
    details: dict[str, Any] | None = None


def _config() -> dict[str, Any]:
    return config_store.get_config().get("watchlist", {})


def _sev(score: float | None, hi: float = 0.7, mid: float = 0.4) -> str:
    return "high" if (score or 0) >= hi else "medium" if (score or 0) >= mid else "low"


# ---------------------------------------------------------------- collectors
def _vessel_hits(db: Session, mmsi: str, since: datetime) -> list[Hit]:
    vessel = db.execute(select(Vessel).where(Vessel.mmsi == mmsi)).scalar_one_or_none()
    if vessel is None:
        return []
    href = f"/maritime/vessel/{vessel.mmsi}"
    hits: list[Hit] = []
    for e in db.execute(select(EvasionEvent).where(EvasionEvent.vessel_id == vessel.id, EvasionEvent.created_at >= since)).scalars():
        hits.append(Hit("evasion_event", e.id, e.timestamp, e.summary or e.event_type, e.severity, href))
    for e in db.execute(select(EvasionEvent).where(EvasionEvent.event_type == "spoofing_cluster", EvasionEvent.vessel_id != vessel.id, EvasionEvent.timestamp >= since,
                                                   cast(EvasionEvent.details, String).contains(f'"mmsi": "{vessel.mmsi}"')).limit(20)).scalars():
        hits.append(Hit("evasion_event", e.id, e.timestamp, f"caught in a GNSS spoofing cluster: {e.summary}", e.severity, href))
    for b in db.execute(select(SanctionsBreach).where(SanctionsBreach.vessel_id == vessel.id, SanctionsBreach.first_detected_at >= since)).scalars():
        hits.append(Hit("sanctions_breach", b.id, b.timestamp, f"{b.sanctioning_authority} {b.breach_type.replace('_', ' ')}: {b.sanctioned_entity_name} ({round((b.match_confidence or 0) * 100)}%)", b.severity, href))
    for p in db.execute(select(PortCallEvent).where(PortCallEvent.vessel_id == vessel.id, PortCallEvent.arrival_time >= since)).scalars():
        flags = ", ".join(f.replace("_", " ") for f in (p.flags_raised or []))
        hits.append(Hit("port_call", p.id, p.arrival_time, f"port call at {p.port_name} ({p.port_country or '?'}){' - ' + flags if flags else ''}", "high" if flags else "low", href))
    for t in db.execute(select(TransshipmentEvent).where(or_(TransshipmentEvent.vessel_a_id == vessel.id, TransshipmentEvent.vessel_b_id == vessel.id), TransshipmentEvent.timestamp >= since)).scalars():
        other = t.vessel_b_mmsi if t.vessel_a_id == vessel.id else t.vessel_a_mmsi
        hits.append(Hit("transshipment", t.id, t.timestamp, f"STS rendezvous with {other} for {t.duration_minutes} min ({round((t.confidence_score or 0) * 100)}%)", _sev(t.confidence_score), href))
    for p in db.execute(select(PscEvent).where(or_(PscEvent.vessel_id == vessel.id, PscEvent.imo == vessel.imo) if vessel.imo else PscEvent.vessel_id == vessel.id, PscEvent.discovered_at >= since)).scalars():
        hits.append(Hit("psc_event", p.id, p.event_date or p.discovered_at, f"{p.event_type} by {p.source.replace('_', ' ')}{' at ' + p.port if p.port else ''}{f' - {p.deficiency_count} deficiencies' if p.deficiency_count else ''}", "high" if p.event_type == "ban" else "medium", href))
    for s in db.execute(select(OilTankerShipment).where(OilTankerShipment.vessel_id == vessel.id, OilTankerShipment.created_at >= since)).scalars():
        hits.append(Hit("shipment", s.id, s.loading_date or s.created_at, f"loaded {s.cargo_type or 'cargo'} at {s.loading_location or '?'} ({s.origin_country or '?'}){' - sanctioned route' if s.sanctioned_route else ''}", "high" if s.sanctioned_route else "low", href))
    for d in db.execute(select(DarkOilIndicator).where(DarkOilIndicator.tanker_id == vessel.id, DarkOilIndicator.detected_at >= since)).scalars():
        hits.append(Hit("dark_oil", d.id, d.detected_at, d.summary or (d.detected_pattern or "").replace("_", " "), d.severity or _sev(d.confidence_score), href))
    return hits


def _entity_hits(db: Session, key: str, since: datetime) -> list[Hit]:
    entity = db.get(SanctionsEntity, int(key)) if key.isdigit() else None
    if entity is None:
        return []
    href = f"/sanctions?entity={entity.id}"
    hits: list[Hit] = []
    for b in db.execute(select(SanctionsBreach).where(SanctionsBreach.sanctioned_entity_id == entity.id, SanctionsBreach.first_detected_at >= since)).scalars():
        hits.append(Hit("sanctions_breach", b.id, b.timestamp, f"vessel {b.vessel_name} ({b.mmsi}) matched: {b.breach_type.replace('_', ' ')} {round((b.match_confidence or 0) * 100)}%", b.severity, f"/maritime/vessel/{b.mmsi}"))
    for ev in db.execute(select(LegalEvent).where(LegalEvent.matched_entity_id == entity.id, LegalEvent.discovered_at >= since)).scalars():
        hits.append(Hit("legal_event", ev.id, ev.event_date or ev.discovered_at, f"{ev.source.replace('_', ' ')}: {ev.title}", "high", "/monitors?tab=legal"))
    for u in db.execute(select(SanctionsUpdate).where(SanctionsUpdate.entity_id == entity.id, SanctionsUpdate.timestamp >= since)).scalars():
        hits.append(Hit("sanctions_update", u.id, u.timestamp, f"{u.authority} {u.update_type.replace('_', ' ')}", "high" if u.update_type in ("new_designation", "relisted", "delisting") else "medium", href))
    addresses = [a for (a,) in db.execute(select(BlockchainWallet.address).where(BlockchainWallet.owner_entity_id == entity.id)).all()]
    if addresses:
        for t in db.execute(select(BlockchainTransaction).where(or_(BlockchainTransaction.from_address.in_(addresses), BlockchainTransaction.to_address.in_(addresses)), BlockchainTransaction.timestamp >= since).limit(50)).scalars():
            hits.append(Hit("transfer", t.id, t.timestamp, f"{t.blockchain} transfer ${round(t.amount_usd or 0):,} {t.token_type or ''}{' - ' + t.suspicious_pattern.replace('_', ' ') if t.suspicious_pattern else ''}", _sev(min(1.0, (t.amount_usd or 0) / 1_000_000), 0.5, 0.05), "/blockchain?q=" + (t.to_address or "")))
    aircraft_ids = [i for (i,) in db.execute(select(Aircraft.id).where(Aircraft.sanctioned_entity_id == entity.id)).all()]
    if aircraft_ids:
        for s in db.execute(select(AircraftSighting).where(AircraftSighting.aircraft_id.in_(aircraft_ids), AircraftSighting.timestamp >= since).limit(50)).scalars():
            hits.append(Hit("sighting", s.id, s.timestamp, f"aircraft {s.registration} seen{' as ' + s.callsign if s.callsign else ''} at {s.latitude:.2f}, {s.longitude:.2f}" if s.latitude is not None else f"aircraft {s.registration} seen", "medium", "/monitors?tab=aviation"))
    return hits


def _name_hits(db: Session, name: str, since: datetime, href: str) -> list[Hit]:
    like = f"%{name}%"
    hits: list[Hit] = []
    for ev in db.execute(select(LegalEvent).where(LegalEvent.title.ilike(like), LegalEvent.discovered_at >= since).limit(50)).scalars():
        hits.append(Hit("legal_event", ev.id, ev.event_date or ev.discovered_at, f"{ev.source.replace('_', ' ')}: {ev.title}", "high", "/monitors?tab=legal"))
    for b in db.execute(select(BreachEvent).where(or_(BreachEvent.victim_name.ilike(like), BreachEvent.victim_domain.ilike(like)), BreachEvent.discovered_at >= since).limit(50)).scalars():
        hits.append(Hit("breach_event", b.id, b.discovered_at, f"{b.source.replace('_', ' ')}: {b.victim_name}{' (' + b.victim_domain + ')' if b.victim_domain else ''}", "high", "/monitors?tab=leaks"))
    return hits


def _wallet_hits(db: Session, address: str, since: datetime) -> list[Hit]:
    hits: list[Hit] = []
    for t in db.execute(select(BlockchainTransaction).where(or_(BlockchainTransaction.from_address == address, BlockchainTransaction.to_address == address), BlockchainTransaction.timestamp >= since).limit(50)).scalars():
        direction = "out" if t.from_address == address else "in"
        hits.append(Hit("transfer", t.id, t.timestamp, f"{t.blockchain} {direction}: ${round(t.amount_usd or 0):,} {t.token_type or ''}{' - ' + t.suspicious_pattern.replace('_', ' ') if t.suspicious_pattern else ''}", _sev(min(1.0, (t.amount_usd or 0) / 1_000_000), 0.5, 0.05), f"/blockchain?q={address}"))
    return hits


def _aircraft_hits(db: Session, registration: str, since: datetime) -> list[Hit]:
    hits: list[Hit] = []
    for s in db.execute(select(AircraftSighting).where(AircraftSighting.registration == registration.upper(), AircraftSighting.timestamp >= since).limit(50)).scalars():
        where = f" at {s.latitude:.2f}, {s.longitude:.2f}" if s.latitude is not None else ""
        hits.append(Hit("sighting", s.id, s.timestamp, f"{registration.upper()} seen{' as ' + s.callsign if s.callsign else ''}{where}{f' - {s.altitude_ft:.0f} ft' if s.altitude_ft else ''}", "medium", "/monitors?tab=aviation"))
    return hits


def _keyword_hits(db: Session, text: str, since: datetime) -> list[Hit]:
    like = f"%{text}%"
    hits = _name_hits(db, text, since, "/monitors")
    for e in db.execute(select(GeopoliticalEvent).where(GeopoliticalEvent.title.ilike(like), GeopoliticalEvent.detected_date >= since).limit(50)).scalars():
        hits.append(Hit("geopolitical_event", e.id, e.event_date, f"{e.event_type.replace('_', ' ')}: {e.title}", e.severity or "medium", "/geopolitical"))
    for n in db.execute(select(Narrative).where(Narrative.topic.ilike(like), Narrative.last_seen >= since).limit(20)).scalars():
        hits.append(Hit("narrative", n.id, n.last_seen, f"narrative across {n.outlet_count or 0} outlets: {n.topic}", "medium", "/monitors?tab=narratives"))
    for p in db.execute(select(PscEvent).where(or_(PscEvent.ship_name.ilike(like), PscEvent.company.ilike(like)), PscEvent.discovered_at >= since).limit(50)).scalars():
        hits.append(Hit("psc_event", p.id, p.event_date or p.discovered_at, f"{p.ship_name}: {p.event_type} by {p.source.replace('_', ' ')}{' at ' + p.port if p.port else ''}", "high" if p.event_type == "ban" else "medium", "/monitors?tab=psc"))
    for u in db.execute(select(SanctionsUpdate).where(SanctionsUpdate.entity_name.ilike(like), SanctionsUpdate.timestamp >= since).limit(50)).scalars():
        hits.append(Hit("sanctions_update", u.id, u.timestamp, f"{u.authority} {u.update_type.replace('_', ' ')}: {u.entity_name}", "high", f"/sanctions?entity={u.entity_id}" if u.entity_id else "/sanctions"))
    return hits


def collect_hits(db: Session, item: WatchlistItem, since: datetime) -> list[Hit]:
    if item.kind == "vessel":
        return _vessel_hits(db, item.key, since)
    if item.kind == "entity":
        return _entity_hits(db, item.key, since)
    if item.kind == "company":
        return _name_hits(db, item.key, since, "/corporate?q=" + item.key)
    if item.kind == "wallet":
        return _wallet_hits(db, item.key, since)
    if item.kind == "aircraft":
        return _aircraft_hits(db, item.key, since)
    if item.kind == "domain":
        return _name_hits(db, item.key, since, "/monitors?tab=infra")
    if item.kind == "keyword":
        return _keyword_hits(db, item.key, since)
    return []


# --------------------------------------------------------------------- bot
class WatchlistBot:
    def __init__(self) -> None:
        self.last_run: datetime | None = None
        self.last_result: dict[str, Any] = {}

    def status(self) -> dict[str, Any]:
        return {"last_run": self.last_run, "last_result": self.last_result}

    async def check(self, item_id: int | None = None) -> dict[str, Any]:
        result = await asyncio.to_thread(self.check_sync, item_id)
        self.last_run = utcnow()
        self.last_result = result
        if result.get("hits"):
            log.info("watchlist: {}", result)
        return result

    @staticmethod
    def check_sync(item_id: int | None = None) -> dict[str, Any]:
        now = utcnow()
        alerts_enabled = _config().get("alerts", True)
        new_hits = 0
        alerted = 0
        with SessionLocal() as db:
            query = select(WatchlistItem).where(WatchlistItem.active.is_(True))
            if item_id is not None:
                query = query.where(WatchlistItem.id == item_id)
            items = db.execute(query).scalars().all()
            for item in items:
                since = item.last_checked_at or max(item.created_at - FIRST_LOOKBACK, now - timedelta(days=30))
                existing = {(r, i) for r, i in db.execute(select(WatchlistHit.record_type, WatchlistHit.record_id).where(WatchlistHit.item_id == item.id)).all()}
                fresh = [h for h in collect_hits(db, item, since) if (h.record_type, h.record_id) not in existing]
                for hit in fresh:
                    db.add(WatchlistHit(item_id=item.id, record_type=hit.record_type, record_id=hit.record_id, timestamp=hit.timestamp, severity=hit.severity, summary=hit.summary[:300], href=hit.href, details=hit.details))
                    existing.add((hit.record_type, hit.record_id))
                if fresh:
                    item.hit_count = (item.hit_count or 0) + len(fresh)
                    item.last_hit_at = max(h.timestamp for h in fresh)
                    new_hits += len(fresh)
                    if item.alert and alerts_enabled and item.last_checked_at is not None:  # the first pass is context, not news
                        WatchlistBot._alert(item, fresh)
                        alerted += 1
                item.last_checked_at = now
            db.commit()
        return {"items": len(items), "hits": new_hits, "alerted": alerted}

    @staticmethod
    def _alert(item: WatchlistItem, hits: list[Hit]) -> None:
        from app import notifications

        rank = {"low": 0, "medium": 1, "high": 2, "critical": 3}
        worst = max(hits, key=lambda h: rank.get(h.severity, 0))
        lines = [f"- [{h.severity}] {h.timestamp:%Y-%m-%d %H:%M}Z {h.summary}" for h in sorted(hits, key=lambda h: h.timestamp, reverse=True)[:8]]
        notifications.send_alert("watchlist", f"Watchlist: {item.label or item.key} ({item.kind}) - {len(hits)} new hit(s)", "\n".join(lines), severity=worst.severity,
                                 data={"item_id": item.id, "kind": item.kind, "key": item.key, "hits": len(hits)})
        try:
            from app.api.stream import manager

            manager.publish("watchlist_hit", {"item_id": item.id, "kind": item.kind, "key": item.key, "label": item.label, "hits": len(hits), "severity": worst.severity, "summary": worst.summary})
        except Exception:  # noqa: BLE001
            pass

    @staticmethod
    def summary(db: Session, days: int = 7) -> dict[str, Any]:
        since = utcnow() - timedelta(days=days)
        items = db.execute(select(func.count(WatchlistItem.id)).where(WatchlistItem.active.is_(True))).scalar() or 0
        by_kind = dict(db.execute(select(WatchlistItem.kind, func.count()).where(WatchlistItem.active.is_(True)).group_by(WatchlistItem.kind)).all())
        hits = db.execute(select(func.count(WatchlistHit.id)).where(WatchlistHit.created_at >= since)).scalar() or 0
        by_severity = dict(db.execute(select(WatchlistHit.severity, func.count()).where(WatchlistHit.created_at >= since).group_by(WatchlistHit.severity)).all())
        return {"days": days, "items": items, "by_kind": by_kind, "hits": hits, "by_severity": by_severity}


watchlist_bot = WatchlistBot()
