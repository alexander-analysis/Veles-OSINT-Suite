"""Cross-domain intelligence brief: one document covering every bot's output for a period."""

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.analysis.correlation_engine import SEVERITY_RANK
from app.bots.correlation import collect_signals
from app.models.blockchain import BlockchainTransaction, BlockchainWallet
from app.models.corporate import Company
from app.models.correlation import CompositeAlert, SignalCorrelation
from app.models.energy import DarkOilIndicator, OilTankerShipment
from app.models.geopolitical import GeopoliticalEvent
from app.models.maritime import SanctionsBreach, Vessel
from app.models.market import MarketAlert
from app.models.tier2 import Aircraft, BreachEvent, InfraAsset, LegalEvent, Narrative
from app.reports.pdf import Report, Section
from app.utils.time import to_iso_z, utcnow


def _fmt(dt: datetime | None) -> str:
    return f"{dt:%d %b %H:%M}" if dt else "-"


def fusion_brief(db: Session, start: datetime, end: datetime, classification: str = "UNCLASSIFIED") -> tuple[Report, dict[str, Any]]:
    signals = collect_signals(db, start, limit_per_type=300)
    signals = [s for s in signals if s.time <= end]
    by_domain: dict[str, int] = {}
    by_severity: dict[str, int] = {}
    for s in signals:
        by_domain[s.domain] = by_domain.get(s.domain, 0) + 1
        by_severity[s.severity] = by_severity.get(s.severity, 0) + 1
    alerts = db.execute(select(CompositeAlert).where(CompositeAlert.detected_at.between(start, end)).order_by(CompositeAlert.detected_at.desc())).scalars().all()
    alerts.sort(key=lambda a: (-SEVERITY_RANK.get(a.severity, 0), -(a.confidence or 0)))
    pairs = db.execute(select(func.count(SignalCorrelation.id)).where(SignalCorrelation.detected_at.between(start, end))).scalar() or 0

    breaches = db.execute(select(SanctionsBreach).where(SanctionsBreach.timestamp.between(start, end)).order_by(SanctionsBreach.match_confidence.desc()).limit(15)).scalars().all()
    geo = db.execute(select(GeopoliticalEvent).where(GeopoliticalEvent.event_date.between(start, end), GeopoliticalEvent.severity.in_(["high", "critical"])).order_by(GeopoliticalEvent.event_date.desc()).limit(15)).scalars().all()
    market = db.execute(select(MarketAlert).where(MarketAlert.timestamp.between(start, end), MarketAlert.severity.in_(["high", "critical"])).order_by(MarketAlert.timestamp.desc()).limit(12)).scalars().all()
    chain_tx = db.execute(select(BlockchainTransaction).where(BlockchainTransaction.timestamp.between(start, end), BlockchainTransaction.involves_sanctioned.is_(True)).order_by(BlockchainTransaction.amount_usd.desc().nulls_last()).limit(12)).scalars().all()
    wallet_balance = db.execute(select(func.sum(BlockchainWallet.balance_usd)).where(BlockchainWallet.is_sanctioned.is_(True))).scalar() or 0.0
    exposure = db.execute(select(Company).where(Company.updated_at.between(start, end), Company.linked_to_sanctioned.is_(True), Company.sanctions_match_type.in_(["parent", "ultimate_parent", "child"])).order_by(Company.risk_score.desc()).limit(12)).scalars().all()
    shipments = db.execute(select(OilTankerShipment).where(OilTankerShipment.loading_date.between(start, end), OilTankerShipment.sanctioned_route.is_(True)).order_by(OilTankerShipment.loading_date.desc()).limit(15)).scalars().all()
    dark = db.execute(select(DarkOilIndicator).where(DarkOilIndicator.detected_at.between(start, end)).order_by(DarkOilIndicator.confidence_score.desc()).limit(12)).scalars().all()
    aircraft = db.execute(select(Aircraft).where(Aircraft.last_seen.between(start, end)).order_by(Aircraft.last_seen.desc()).limit(12)).scalars().all()
    breaches_cyber = db.execute(select(BreachEvent).where(BreachEvent.discovered_at.between(start, end), BreachEvent.relevance_score >= 0.6).order_by(BreachEvent.relevance_score.desc()).limit(12)).scalars().all()
    narratives = db.execute(select(Narrative).where(Narrative.last_seen.between(start, end)).order_by(Narrative.score.desc()).limit(8)).scalars().all()
    legal = db.execute(select(LegalEvent).where(or_(LegalEvent.event_date.between(start, end), LegalEvent.discovered_at.between(start, end))).order_by(LegalEvent.event_date.desc().nulls_last()).limit(12)).scalars().all()
    infra_live = db.execute(select(func.count(InfraAsset.id)).where(InfraAsset.is_live.is_(True))).scalar() or 0
    vessels_active = db.execute(select(func.count(Vessel.id)).where(Vessel.last_ais_update >= end - timedelta(hours=24))).scalar() or 0

    report = Report(title="VELES Cross-Domain Intelligence Brief", subtitle="Market, sanctions, maritime, geopolitical, blockchain, corporate, energy, aviation, cyber, information and legal signals - fused", classification=classification,
                    period=f"{start:%Y-%m-%d %H:%M} to {end:%Y-%m-%d %H:%M} UTC")
    summary = (
        f"{len(signals)} signals from {len(by_domain)} collection domains were recorded in the period ({', '.join(f'{k} {v}' for k, v in sorted(by_domain.items(), key=lambda kv: -kv[1]))}); "
        f"{by_severity.get('critical', 0)} critical and {by_severity.get('high', 0)} high. The fusion engine recorded {pairs} cross-domain links and {len(alerts)} composite alert(s). "
        f"{vessels_active:,} vessels were active on AIS in the last 24 hours; ${wallet_balance:,.0f} sits in wallets tied to listed parties; {infra_live} listed-party domains resolve."
    )
    report.sections.append(Section("Executive summary", text=summary, items=[("Signals", len(signals)), ("Cross-domain links", pairs), ("Composite alerts", len(alerts)), ("Critical / high signals", f"{by_severity.get('critical', 0)} / {by_severity.get('high', 0)}")]))
    if alerts:
        report.sections.append(Section("Composite alerts", table=[["Severity", "Title", "Domains", "Signals", "Confidence"], *[[a.severity, a.title, ", ".join(a.domains), len(a.signals or []), f"{(a.confidence or 0):.2f}"] for a in alerts[:12]]], column_widths=[18, 78, 44, 16, 20]))
        for a in alerts[:5]:
            report.sections.append(Section(f"Alert: {a.title}", text=a.intelligence_summary or ""))
    if breaches:
        report.sections.append(Section("Maritime - sanctions matches", table=[["When", "Vessel", "Flag", "Authority", "Listed party", "Conf."], *[[_fmt(b.timestamp), b.vessel_name, b.flag, b.sanctioning_authority, b.sanctioned_entity_name, f"{(b.match_confidence or 0):.2f}"] for b in breaches]], page_break_before=True))
    if shipments or dark:
        rows = [["Loaded", "Vessel", "Flag", "Facility", "Cargo", "Destination", "Dark oil"], *[[_fmt(s.loading_date), s.vessel_name, s.flag, s.loading_location, s.cargo_type, s.discharge_location or "-", "yes" if s.dark_oil_suspect else ""] for s in shipments]]
        report.sections.append(Section("Energy - sanctioned-route shipments", table=rows if shipments else None, text=None if shipments else "No sanctioned-route shipments reconstructed in the period."))
        if dark:
            report.sections.append(Section("Energy - dark-oil indicators", table=[["When", "Pattern", "Tanker", "Conf.", "Summary"], *[[_fmt(d.detected_at), d.detected_pattern, d.tanker_name, f"{(d.confidence_score or 0):.2f}", (d.summary or "")[:90]] for d in dark]], column_widths=[18, 34, 34, 14, 76]))
    if geo:
        report.sections.append(Section("Geopolitical - high / critical events", table=[["When", "Type", "Country", "Severity", "Title"], *[[_fmt(g.event_date), g.event_type, g.country_primary or "-", g.severity, g.title[:90]] for g in geo]], column_widths=[18, 26, 16, 16, 100]))
    if market:
        report.sections.append(Section("Market - high / critical alerts", table=[["When", "Asset", "Type", "Severity", "Summary"], *[[_fmt(m.timestamp), m.asset, m.alert_type, m.severity, (m.summary or "")[:90]] for m in market]]))
    if chain_tx:
        report.sections.append(Section("Blockchain - transfers touching listed wallets", table=[["When", "Chain", "USD", "Pattern", "From", "To"], *[[_fmt(t.timestamp), t.blockchain, f"{(t.amount_usd or 0):,.0f}", t.suspicious_pattern, (t.source_entity or t.from_address or "")[:28], (t.destination_entity or t.to_address or "")[:28]] for t in chain_tx]]))
    if exposure:
        report.sections.append(Section("Corporate - new sanctions exposure", table=[["Company", "Country", "Link", "Risk"], *[[c.company_name[:60], c.registration_country or "-", (c.sanctions_match_type or "").replace("_", " "), f"{(c.risk_score or 0):.2f}"] for c in exposure]]))
    if aircraft:
        report.sections.append(Section("Aviation - listed airframes observed", table=[["Last seen", "Registration", "Operator", "Model", "Callsign", "Position"], *[[_fmt(a.last_seen), a.registration, a.operator or "-", a.model or "-", a.last_callsign or "-", f"{a.last_lat:.2f}, {a.last_lon:.2f}" if a.last_lat is not None else "-"] for a in aircraft]]))
    if breaches_cyber:
        report.sections.append(Section("Cyber - relevant breach / ransomware postings", table=[["Discovered", "Victim", "Country", "Actor", "Relevance", "Score"], *[[_fmt(b.discovered_at), b.victim_name[:40], b.country or "-", b.threat_actor or b.source, (b.relevance or "").replace("_", " "), f"{(b.relevance_score or 0):.2f}"] for b in breaches_cyber]]))
    if narratives:
        report.sections.append(Section("Information - state-media narratives", table=[["Last seen", "Divergence", "Topic", "Items / outlets", "Score"], *[[_fmt(n.last_seen), n.divergence, n.topic[:60], f"{n.item_count} / {n.outlet_count}", f"{(n.score or 0):.2f}"] for n in narratives]]))
    if legal:
        report.sections.append(Section("Legal - enforcement, prosecutions, dockets", table=[["Date", "Source", "Type", "Title", "Listed party"], *[[_fmt(e.event_date), e.source, e.event_type or "-", e.title[:70], e.matched_entity_name or "-"] for e in legal]], column_widths=[18, 26, 20, 72, 40]))
    method = (
        "Signals are collected from every VELES bot and keyed by vessel, listed party, wallet, company, facility, aircraft, domain, country and asset. Pairs sharing a strong key inside the window are scored; "
        "clusters spanning three or more domains become composite alerts. All sources are open (OFAC / EU / UN lists, AIS, GDELT, public blockchain APIs, GLEIF, ADS-B, ransomware.live, HIBP, RDAP, crt.sh, CourtListener, DOJ, OFAC). "
        "Confidence values are analytic prioritisation scores, not legal findings."
    )
    report.sections.append(Section("Method", text=method))
    data = {
        "classification": classification, "period": {"start": to_iso_z(start), "end": to_iso_z(end)}, "generated_at": to_iso_z(utcnow()), "summary": summary,
        "signals": {"total": len(signals), "by_domain": by_domain, "by_severity": by_severity}, "correlations": pairs,
        "composite_alerts": [{"id": a.id, "title": a.title, "severity": a.severity, "confidence": a.confidence, "domains": a.domains, "signals": len(a.signals or []), "summary": a.intelligence_summary} for a in alerts],
        "sections": [s.title for s in report.sections],
    }
    return report, data
