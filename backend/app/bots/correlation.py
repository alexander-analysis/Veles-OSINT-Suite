"""Cross-bot correlation engine (ecosystem Part 4).

Every five minutes the outputs of all bots inside the window are reduced to
signals, correlated pairwise across domains (shared vessels, listed parties,
wallets, companies, facilities, countries, assets) and clustered; clusters
spanning three or more domains are stored as composite alerts.  The unified
queue and timeline views for the dashboard are built here too.
"""

import asyncio
import re
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.analysis.correlation_engine import SEVERITY_RANK, Signal, clusters, correlate, narrative, title_for
from app.analysis.geopolitical import ASSET_SECTORS
from app.data.energy_facilities import FACILITIES
from app.database import SessionLocal
from app.models.audit import AuditLog
from app.models.blockchain import BlockchainTransaction, BlockchainWallet
from app.models.corporate import Company
from app.models.correlation import CompositeAlert, SignalCorrelation
from app.models.energy import DarkOilIndicator, OilTankerShipment
from app.models.geopolitical import GeopoliticalEvent
from app.models.maritime import EvasionEvent, PortCallEvent, SanctionsBreach, TransshipmentEvent, Vessel
from app.models.market import CoordinationEvent, LiquidationCascade, MarketAlert
from app.models.sanctions import SanctionsEntity, SanctionsUpdate
from app.models.tier2 import AircraftSighting, BreachEvent, InfraAsset, LegalEvent, Narrative, PscEvent
from app.utils import config_store
from app.utils.logger import logger
from app.utils.time import utcnow

log = logger.bind(component="fusion")


def _config() -> dict[str, Any]:
    return config_store.get_config().get("correlation", {})


# facility name -> canonical key; port names and distinctive first tokens map onto the same key
_FACILITY_BY_PORT = {f["port_name"]: f["name"] for f in FACILITIES if f.get("port_name")}
_FACILITY_TOKENS = [(f["name"], f["name"].split("(")[0].split()[0].lower()) for f in FACILITIES if len(f["name"].split("(")[0].split()[0]) >= 5]


def facility_key(name: str | None) -> str | None:
    if not name:
        return None
    return _FACILITY_BY_PORT.get(name, name)


def facilities_in_text(text: str | None) -> list[str]:
    lowered = (text or "").lower()
    return [name for name, token in _FACILITY_TOKENS if re.search(rf"\b{re.escape(token)}\b", lowered)]


def _sev(confidence: float | None, high: float = 0.8, medium: float = 0.5) -> str:
    c = confidence or 0
    return "high" if c >= high else "medium" if c >= medium else "low"


# ---------------------------------------------------------------- collectors
def collect_signals(db: Session, since: datetime, limit_per_type: int = 400) -> list[Signal]:
    signals: list[Signal] = []

    for a in db.execute(select(MarketAlert).where(MarketAlert.timestamp >= since).order_by(MarketAlert.timestamp.desc()).limit(limit_per_type)).scalars():
        s = Signal("market_alert", a.id, a.timestamp, a.summary or f"{a.asset} {a.alert_type} ({a.severity})", a.severity)
        s.add("asset", a.asset)
        s.add("sector", ASSET_SECTORS.get(a.asset, "finance"))
        signals.append(s)
    for c in db.execute(select(CoordinationEvent).where(CoordinationEvent.detected_at >= since).limit(limit_per_type)).scalars():
        s = Signal("coordination_event", c.id, c.detected_at, c.summary or f"{c.asset} coordinated move on {', '.join(c.exchanges or [])}", _sev(c.confidence_score))
        s.add("asset", c.asset)
        s.add("sector", ASSET_SECTORS.get(c.asset, "finance"))
        signals.append(s)
    for lc in db.execute(select(LiquidationCascade).where(LiquidationCascade.timestamp >= since).limit(limit_per_type)).scalars():
        s = Signal("liquidation_cascade", lc.id, lc.timestamp, lc.summary or f"{lc.asset} liquidation cascade ${(lc.total_liquidated_usd or 0):,.0f}", "high" if (lc.total_liquidated_usd or 0) >= 10_000_000 else "medium")
        s.add("asset", lc.asset)
        s.add("sector", "finance")
        signals.append(s)

    vessel_flags: dict[int, str] = {}

    def flag_of(vessel_id: int | None) -> str | None:
        if vessel_id is None:
            return None
        if vessel_id not in vessel_flags:
            vessel_flags[vessel_id] = db.execute(select(Vessel.flag_state).where(Vessel.id == vessel_id)).scalar()
        return vessel_flags.get(vessel_id)

    entity_country: dict[int, str | None] = {}

    def country_of_entity(entity_id: int | None) -> str | None:
        if entity_id is None:
            return None
        if entity_id not in entity_country:
            entity_country[entity_id] = db.execute(select(SanctionsEntity.country_linked).where(SanctionsEntity.id == entity_id)).scalar()
        return entity_country.get(entity_id)

    for b in db.execute(select(SanctionsBreach).where(SanctionsBreach.timestamp >= since, SanctionsBreach.investigation_status != "cleared").limit(limit_per_type)).scalars():
        s = Signal("sanctions_breach", b.id, b.timestamp, f"{b.sanctioning_authority} match: {b.vessel_name} ({b.flag}) -> {b.sanctioned_entity_name} ({(b.match_confidence or 0):.2f})", b.severity)
        s.add("vessel", b.mmsi)
        s.add("entity", b.sanctioned_entity_name, b.vessel_name)
        s.add("country", b.flag, country_of_entity(b.sanctioned_entity_id))
        s.add("sector", "shipping")
        s.add("theme", "sanctions")
        signals.append(s)
    for e in db.execute(select(EvasionEvent).where(EvasionEvent.timestamp >= since).limit(limit_per_type)).scalars():
        s = Signal("evasion_event", e.id, e.timestamp, e.summary or f"{e.event_type} {e.mmsi}", e.severity)
        s.add("vessel", e.mmsi)
        s.add("country", flag_of(e.vessel_id))
        s.add("sector", "shipping")
        signals.append(s)
    for t in db.execute(select(TransshipmentEvent).where(TransshipmentEvent.timestamp >= since).limit(limit_per_type)).scalars():
        s = Signal("transshipment", t.id, t.timestamp, f"STS candidate {t.vessel_a_mmsi} / {t.vessel_b_mmsi} ({(t.confidence_score or 0):.2f})", _sev(t.confidence_score))
        s.add("vessel", t.vessel_a_mmsi, t.vessel_b_mmsi)
        s.add("country", flag_of(t.vessel_a_id), flag_of(t.vessel_b_id))
        s.add("sector", "shipping")
        s.add("theme", "maritime")
        signals.append(s)
    for p, v in db.execute(select(PortCallEvent, Vessel).join(Vessel, Vessel.id == PortCallEvent.vessel_id).where(PortCallEvent.arrival_time >= since, PortCallEvent.is_sanctioned_facility.is_(True)).limit(limit_per_type)).all():
        s = Signal("port_call", p.id, p.arrival_time, f"{v.name} ({v.flag_state}) called at sanctioned facility {p.port_name} ({p.port_country})", "high" if (v.sanctioned_status or "clear") != "clear" else "medium")
        s.add("vessel", p.mmsi)
        s.add("country", p.port_country, v.flag_state)
        s.add("facility", facility_key(p.port_name))
        s.add("sector", "shipping", "energy")
        signals.append(s)

    for u in db.execute(select(SanctionsUpdate).where(SanctionsUpdate.timestamp >= since, SanctionsUpdate.update_type.in_(["new_designation", "relisted"])).limit(limit_per_type)).scalars():
        s = Signal("sanctions_update", u.id, u.timestamp, f"{u.authority} {u.update_type}: {u.entity_name}", "medium")
        s.add("entity", u.entity_name)
        s.add("country", country_of_entity(u.entity_id))
        s.add("theme", "sanctions")
        s.add("sector", "finance")
        signals.append(s)

    # vessels already in play (breaches, evasion, STS, port calls) whose names are distinctive enough to spot in a headline
    vessel_names: dict[str, str] = {}
    mmsis = sorted({m for sig in signals for m in sig.keys.get("vessel", ())})
    for i in range(0, len(mmsis), 500):
        for mmsi, name in db.execute(select(Vessel.mmsi, Vessel.name).where(Vessel.mmsi.in_(mmsis[i:i + 500]))).all():
            if name and (len(name) >= 8 or " " in name.strip()) and not name.upper().startswith(("UNKNOWN", "TANKER", "VESSEL")):
                vessel_names[name.upper()] = mmsi
    for g in db.execute(select(GeopoliticalEvent).where(GeopoliticalEvent.event_date >= since, GeopoliticalEvent.severity.in_(["medium", "high", "critical"])).limit(limit_per_type)).scalars():
        s = Signal("geopolitical_event", g.id, g.event_date, g.title, g.severity or "medium")
        s.add("country", g.country_primary, g.country_secondary, *(g.affected_countries or []))
        s.add("sector", *(g.affected_sectors or []))
        s.add("facility", *facilities_in_text(g.title))
        title_upper = f" {g.title.upper()} "
        s.add("vessel", *(mmsi for name, mmsi in vessel_names.items() if f" {name} " in title_upper))
        if g.event_type == "sanctions":
            s.add("theme", "sanctions")
        if g.event_type in ("maritime_incident", "port_closure"):
            s.add("theme", "maritime")
        signals.append(s)

    txs = db.execute(select(BlockchainTransaction).where(BlockchainTransaction.timestamp >= since, or_(BlockchainTransaction.involves_sanctioned.is_(True), BlockchainTransaction.involves_mixer.is_(True))).limit(limit_per_type)).scalars().all()
    if txs:
        addresses = {a for t in txs for a in (t.from_address, t.to_address) if a}
        wallets = {(w.blockchain, w.address): w for w in db.execute(select(BlockchainWallet).where(BlockchainWallet.address.in_(list(addresses)[:900]))).scalars()}
        for t in txs:
            s = Signal("blockchain_tx", t.id, t.timestamp, f"{(t.suspicious_pattern or 'transfer').replace('_', ' ')}: ${(t.amount_usd or 0):,.0f} {t.token_type} {t.source_entity or 'unlabelled'} -> {t.destination_entity or 'unlabelled'}",
                       "critical" if (t.risk_score or 0) >= 0.9 else "high" if t.involves_sanctioned else "medium")
            s.add("entity", t.source_entity, t.destination_entity)
            s.add("wallet", t.from_address, t.to_address)
            s.add("asset", t.token_type)
            s.add("sector", "finance")
            s.add("theme", "sanctions" if t.involves_sanctioned else "crypto")
            for address in (t.from_address, t.to_address):
                w = wallets.get((t.blockchain, address))
                if w and w.owner_entity_id:
                    s.add("country", country_of_entity(w.owner_entity_id))
            signals.append(s)

    for c in db.execute(select(Company).where(Company.updated_at >= since, Company.linked_to_sanctioned.is_(True), Company.sanctions_match_type.in_(["parent", "ultimate_parent", "child"])).limit(limit_per_type)).scalars():
        listed = db.execute(select(SanctionsEntity.name).where(SanctionsEntity.id == c.sanctioned_entity_id)).scalar() if c.sanctioned_entity_id else None
        s = Signal("corporate_exposure", c.id, c.updated_at, f"{c.company_name} ({c.registration_country}) is {c.sanctions_match_type.replace('_', ' ')} of listed {listed or 'party'}", "high" if (c.risk_score or 0) >= 0.8 else "medium")
        s.add("company", c.company_name)
        s.add("entity", listed, c.company_name)
        s.add("country", c.registration_country, country_of_entity(c.sanctioned_entity_id))
        s.add("theme", "sanctions")
        signals.append(s)

    for d in db.execute(select(DarkOilIndicator).where(DarkOilIndicator.detected_at >= since, DarkOilIndicator.investigation_status != "cleared").limit(limit_per_type)).scalars():
        s = Signal("dark_oil", d.id, d.detected_at, d.summary or d.detected_pattern, d.severity or "medium")
        s.add("vessel", d.mmsi)
        s.add("country", d.suspected_origin, d.suspected_destination)
        s.add("facility", facility_key((d.evidence or {}).get("facility")))
        s.add("sector", "energy", "shipping")
        s.add("theme", "maritime")
        signals.append(s)
    for sh in db.execute(select(OilTankerShipment).where(OilTankerShipment.loading_date >= since, OilTankerShipment.sanctioned_route.is_(True)).limit(limit_per_type)).scalars():
        s = Signal("oil_shipment", sh.id, sh.loading_date, f"{sh.vessel_name} ({sh.flag}) loaded {sh.cargo_type} at {sh.loading_location}" + (f" -> {sh.discharge_location}" if sh.discharge_location else ""), "high" if sh.dark_oil_suspect else "medium")
        s.add("vessel", sh.mmsi)
        s.add("country", sh.origin_country, sh.destination_country)
        s.add("facility", facility_key(sh.loading_location), facility_key(sh.discharge_location))
        s.add("sector", "energy", "shipping")
        signals.append(s)

    # ---- tier 2 / 3
    seen_flights: set[str] = set()
    for sighting in db.execute(select(AircraftSighting).where(AircraftSighting.timestamp >= since).order_by(AircraftSighting.timestamp.desc()).limit(limit_per_type * 3)).scalars():
        if sighting.flight_key in seen_flights:
            continue  # one signal per flight, not per fix
        seen_flights.add(sighting.flight_key)
        aircraft = sighting.aircraft
        s = Signal("aircraft_sighting", sighting.id, sighting.timestamp, f"{sighting.registration} ({aircraft.operator if aircraft else '?'}) airborne {sighting.nearest_place or ''} as {sighting.callsign or '-'}", "high" if aircraft and aircraft.is_sanctioned else "medium")
        s.add("aircraft", sighting.registration)
        s.add("entity", aircraft.operator if aircraft else None)
        s.add("country", aircraft.country if aircraft else None)
        s.add("sector", "aviation")
        signals.append(s)
    for b in db.execute(select(BreachEvent).where(BreachEvent.discovered_at >= since, BreachEvent.relevance_score >= 0.6).limit(limit_per_type)).scalars():
        s = Signal("breach", b.id, b.discovered_at, f"{b.victim_name} ({b.country or '?'}) - {(b.relevance or '').replace('_', ' ')} - {b.threat_actor or b.source}", b.severity or "medium")
        s.add("company", b.victim_name)
        s.add("entity", b.victim_name)
        s.add("domain", b.victim_domain)
        s.add("country", b.country)
        s.add("sector", (b.sector or "").lower()[:30] or None, "cyber")
        signals.append(s)
    for n in db.execute(select(Narrative).where(Narrative.last_seen >= since, Narrative.score >= 0.5).limit(limit_per_type)).scalars():
        s = Signal("narrative", n.id, n.last_seen, f"State-media narrative ({n.divergence}): {n.topic} - {n.item_count} items / {n.outlet_count} outlets", n.severity or "medium")
        s.add("country", *(n.countries or []))
        s.add("theme", "narrative")
        s.add("sector", *(k for k in (n.keywords or []) if k in ("oil", "gas", "tanker", "sanctions", "pipeline", "port")))
        signals.append(s)
    for e in db.execute(select(LegalEvent).where(LegalEvent.discovered_at >= since).limit(limit_per_type)).scalars():
        s = Signal("legal_event", e.id, e.event_date or e.discovered_at, e.title, "high" if e.matched_entity_id or (e.penalty_usd or 0) >= 1_000_000 else "medium")
        s.add("entity", e.matched_entity_name, *(e.details or {}).get("parties", [])[:10])
        s.add("theme", "sanctions" if e.source in ("ofac_enforcement", "courtlistener") else "legal")
        signals.append(s)
    for e in db.execute(select(PscEvent).where(PscEvent.discovered_at >= since, PscEvent.relevance_score >= 0.45).limit(limit_per_type)).scalars():
        mmsi = db.execute(select(Vessel.mmsi).where(Vessel.id == e.vessel_id)).scalar() if e.vessel_id else None
        s = Signal("psc_event", e.id, e.event_date or e.discovered_at, f"{e.ship_name} ({e.flag or '?'}) {e.event_type} by {e.source.replace('_', ' ')}{' at ' + e.port if e.port else ''}" + (f" - {e.deficiency_count} deficiencies" if e.deficiency_count else ""),
                   "high" if e.vessel_flagged else "medium")
        s.add("vessel", mmsi)
        s.add("entity", e.company, e.ship_name if e.vessel_flagged else None)
        s.add("country", e.flag, e.port_country)
        s.add("sector", "shipping")
        signals.append(s)
    for a in db.execute(select(InfraAsset).where(InfraAsset.last_checked >= since, InfraAsset.is_live.is_(True), InfraAsset.risk_score >= 0.6).limit(limit_per_type)).scalars():
        s = Signal("infra_asset", a.id, a.last_checked, f"{a.value} live for listed party {a.entity_name or '?'} - hosted {a.hosting_country or '?'} ({a.asn_org or '?'})", "medium")
        s.add("domain", a.value)
        s.add("entity", a.entity_name)
        s.add("country", a.hosting_country)
        s.add("theme", "sanctions")
        signals.append(s)
    return signals


class CorrelationEngine:
    def __init__(self) -> None:
        self.last_run: datetime | None = None
        self.last_result: dict[str, Any] = {}

    def status(self) -> dict[str, Any]:
        return {"last_run": self.last_run, "last_result": self.last_result}

    async def run(self) -> dict[str, Any]:
        cfg = _config()
        if not cfg.get("enabled", True):
            return {"skipped": "disabled"}
        result = await asyncio.to_thread(self._run, float(cfg.get("window_hours", 48)), float(cfg.get("min_pair_score", 0.45)), int(cfg.get("min_domains", 3)))
        self.last_run = utcnow()
        self.last_result = result
        log.info("fusion: {}", result)
        return result

    def _run(self, window_hours: float, min_score: float, min_domains: int) -> dict[str, Any]:
        now = utcnow()
        since = now - timedelta(hours=window_hours)
        with SessionLocal() as db:
            signals = collect_signals(db, since)
            pairs = correlate(signals, window_hours, min_score)
            existing = {
                (r.signal_a_type, r.signal_a_id, r.signal_b_type, r.signal_b_id)
                for r in db.execute(select(SignalCorrelation.signal_a_type, SignalCorrelation.signal_a_id, SignalCorrelation.signal_b_type, SignalCorrelation.signal_b_id).where(SignalCorrelation.detected_at >= since - timedelta(hours=window_hours))).all()
            }
            new_pairs = 0
            for pair in pairs:
                a, b = (pair.a, pair.b) if pair.a.ref <= pair.b.ref else (pair.b, pair.a)
                key = (a.type, a.id, b.type, b.id)
                if key in existing:
                    continue
                existing.add(key)
                db.add(SignalCorrelation(signal_a_type=a.type, signal_a_id=a.id, signal_a_summary=a.summary[:300], signal_a_time=a.time, signal_b_type=b.type, signal_b_id=b.id, signal_b_summary=b.summary[:300], signal_b_time=b.time,
                                         correlation_type=f"{a.domain}_{b.domain}", time_delta_minutes=abs(pair.delta_minutes), shared_keys=pair.shared, confidence=pair.score,
                                         rationale=f"{pair.correlation_type} link via {', '.join(pair.shared[:4])}; {abs(pair.delta_minutes)} min apart", detected_at=now))
                new_pairs += 1
            found = clusters(pairs, min_domains)
            existing_alerts = {a.fingerprint: a for a in db.execute(select(CompositeAlert).where(CompositeAlert.window_start >= since - timedelta(days=2))).scalars()}
            new_alerts = updated_alerts = 0
            for cluster in found:
                payload = [{"type": s.type, "id": s.id, "summary": s.summary[:300], "time": s.time.isoformat() + "Z", "severity": s.severity, "domain": s.domain} for s in cluster.signals]
                alert = existing_alerts.get(cluster.fingerprint)
                if alert is None:
                    alert = CompositeAlert(title=title_for(cluster), domains=cluster.domains, signals=payload, shared_keys=cluster.shared, window_start=cluster.window_start, window_end=cluster.window_end,
                                           confidence=cluster.confidence, severity=cluster.severity, intelligence_summary=narrative(cluster), fingerprint=cluster.fingerprint, detected_at=now)
                    db.add(alert)
                    existing_alerts[cluster.fingerprint] = alert
                    new_alerts += 1
                    db.add(AuditLog(action_type="composite_alert", user_id="system", rationale=alert.title, supporting_data={"domains": cluster.domains, "signals": len(payload), "confidence": cluster.confidence, "anchor": cluster.anchor},
                                    source_systems=["bots.correlation"], created_by="system"))
                    if cluster.severity in ("high", "critical"):
                        from app import notifications

                        notifications.send_alert("fusion", alert.title, alert.intelligence_summary[:1500], severity=cluster.severity, data={"domains": ", ".join(cluster.domains), "signals": len(payload)})
                elif len(payload) != len(alert.signals or []) or cluster.severity != alert.severity:
                    alert.signals, alert.domains, alert.shared_keys = payload, cluster.domains, cluster.shared
                    alert.window_end, alert.confidence, alert.severity = cluster.window_end, cluster.confidence, cluster.severity
                    alert.intelligence_summary = narrative(cluster)
                    updated_alerts += 1
            db.commit()
            try:
                from app.api.stream import manager

                if new_alerts:
                    manager.publish("composite_alerts", {"new": new_alerts})
            except Exception:  # noqa: BLE001
                pass
        by_domain: dict[str, int] = defaultdict(int)
        for s in signals:
            by_domain[s.domain] += 1
        return {"signals": len(signals), "by_domain": dict(by_domain), "pairs": len(pairs), "new_pairs": new_pairs, "clusters": len(found), "new_alerts": new_alerts, "updated_alerts": updated_alerts}

    # --------------------------------------------------------------- views
    @staticmethod
    def queue(db: Session, hours: int = 24, min_severity: str = "low", domains: list[str] | None = None, limit: int = 200) -> dict[str, Any]:
        since = utcnow() - timedelta(hours=hours)
        signals = collect_signals(db, since, limit_per_type=limit)
        floor = SEVERITY_RANK.get(min_severity, 0)
        links: dict[str, int] = defaultdict(int)
        for r in db.execute(select(SignalCorrelation.signal_a_type, SignalCorrelation.signal_a_id, SignalCorrelation.signal_b_type, SignalCorrelation.signal_b_id).where(SignalCorrelation.detected_at >= since - timedelta(hours=48))).all():
            links[f"{r[0]}:{r[1]}"] += 1
            links[f"{r[2]}:{r[3]}"] += 1
        items = [
            {"type": s.type, "id": s.id, "domain": s.domain, "time": s.time, "severity": s.severity, "summary": s.summary, "correlations": links.get(s.ref, 0),
             "keys": {k: sorted(v)[:6] for k, v in s.keys.items() if k in ("vessel", "entity", "country", "asset", "facility", "company")}}
            for s in signals
            if SEVERITY_RANK.get(s.severity, 0) >= floor and (not domains or s.domain in domains)
        ]
        items.sort(key=lambda i: (-SEVERITY_RANK.get(i["severity"], 0), -i["correlations"], -i["time"].timestamp()))
        by_domain: dict[str, int] = defaultdict(int)
        for i in items:
            by_domain[i["domain"]] += 1
        return {"hours": hours, "total": len(items), "by_domain": dict(by_domain), "items": items[:limit]}

    @staticmethod
    def timeline(db: Session, hours: int = 48, bucket_hours: int = 1) -> dict[str, Any]:
        since = utcnow() - timedelta(hours=hours)
        signals = collect_signals(db, since, limit_per_type=2000)
        buckets: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        for s in signals:
            slot = s.time.replace(minute=0, second=0, microsecond=0)
            slot = slot.replace(hour=(slot.hour // bucket_hours) * bucket_hours)
            buckets[slot.isoformat() + "Z"][s.domain] += 1
        domains = sorted({s.domain for s in signals})
        return {"hours": hours, "bucket_hours": bucket_hours, "domains": domains, "buckets": [{"time": t, **counts} for t, counts in sorted(buckets.items())]}

    @staticmethod
    def summary(db: Session, hours: int = 24) -> dict[str, Any]:
        since = utcnow() - timedelta(hours=hours)
        alerts = db.execute(select(CompositeAlert).where(CompositeAlert.detected_at >= since)).scalars().all()
        open_alerts = [a for a in alerts if not a.acknowledged]
        pairs = db.execute(select(func.count(SignalCorrelation.id)).where(SignalCorrelation.detected_at >= since)).scalar() or 0
        by_type = dict(db.execute(select(SignalCorrelation.correlation_type, func.count()).where(SignalCorrelation.detected_at >= since).group_by(SignalCorrelation.correlation_type)).all())
        return {
            "hours": hours,
            "composite_alerts": len(alerts),
            "open_composite_alerts": len(open_alerts),
            "critical_open": sum(1 for a in open_alerts if a.severity == "critical"),
            "correlations": pairs,
            "correlations_by_type": by_type,
            "top_alerts": [{"id": a.id, "title": a.title, "severity": a.severity, "confidence": a.confidence, "domains": a.domains, "signals": len(a.signals or []), "detected_at": a.detected_at} for a in sorted(open_alerts, key=lambda a: (-SEVERITY_RANK.get(a.severity, 0), -(a.confidence or 0)))[:5]],
        }


correlation_engine = CorrelationEngine()
