"""Report content builders: maritime / sanctions / market intelligence briefs.

Each builder returns a ``Report`` (rendered to PDF by ``app.reports.pdf``)
and a plain-dict version of the same content for JSON export.
"""

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models.audit import AuditLog
from app.models.maritime import EvasionEvent, PortCallEvent, SanctionsBreach, ShippingLaneViolation, TransshipmentEvent, Vessel
from app.models.market import CoordinationEvent, MarketAlert, MarketCandle
from app.reports.pdf import Report, Section
from app.utils.time import to_iso_z, utcnow

ALL_MARITIME_SECTIONS = ["executive_summary", "breach_analysis", "vessel_profiles", "evasion", "transshipment", "port_activity", "zone_activity", "audit_entries", "recommendations"]


def _period(start: datetime, end: datetime) -> str:
    return f"{start:%Y-%m-%d %H:%M} to {end:%Y-%m-%d %H:%M} UTC"


# ------------------------------------------------------------------ maritime
def maritime_report(db: Session, start: datetime, end: datetime, sections: list[str] | None = None, classification: str = "UNCLASSIFIED", vessel_id: int | None = None) -> tuple[Report, dict[str, Any]]:
    wanted = set(sections or ALL_MARITIME_SECTIONS)
    breach_query = select(SanctionsBreach).where(SanctionsBreach.timestamp.between(start, end))
    if vessel_id:
        breach_query = breach_query.where(SanctionsBreach.vessel_id == vessel_id)
    breaches = db.execute(breach_query.order_by(SanctionsBreach.match_confidence.desc())).scalars().all()
    evasion = db.execute(select(EvasionEvent).where(EvasionEvent.timestamp.between(start, end)).order_by(EvasionEvent.timestamp.desc())).scalars().all()
    sts = db.execute(select(TransshipmentEvent).where(TransshipmentEvent.timestamp.between(start, end)).order_by(TransshipmentEvent.confidence_score.desc())).scalars().all()
    calls = db.execute(select(PortCallEvent).where(PortCallEvent.arrival_time.between(start, end), or_(PortCallEvent.is_sanctioned_facility.is_(True), PortCallEvent.facility_risk_level == "high")).order_by(PortCallEvent.arrival_time.desc())).scalars().all()
    lanes = db.execute(select(ShippingLaneViolation).where(ShippingLaneViolation.timestamp.between(start, end)).order_by(ShippingLaneViolation.timestamp.desc())).scalars().all()
    tracked = db.execute(select(func.count(Vessel.id))).scalar() or 0
    active = db.execute(select(func.count(Vessel.id)).where(Vessel.last_ais_update >= end - timedelta(hours=24))).scalar() or 0
    top_vessels = db.execute(select(Vessel).where(Vessel.risk_score > 0).order_by(Vessel.risk_score.desc()).limit(12)).scalars().all()
    audit_query = select(AuditLog).where(AuditLog.timestamp.between(start, end))
    if vessel_id:
        audit_query = audit_query.where(AuditLog.vessel_id == vessel_id)
    audit = db.execute(audit_query.order_by(AuditLog.timestamp.desc()).limit(80)).scalars().all()

    by_authority: dict[str, int] = {}
    by_severity: dict[str, int] = {}
    for b in breaches:
        by_authority[b.sanctioning_authority] = by_authority.get(b.sanctioning_authority, 0) + 1
        by_severity[b.severity] = by_severity.get(b.severity, 0) + 1
    evasion_by_type: dict[str, int] = {}
    for e in evasion:
        evasion_by_type[e.event_type] = evasion_by_type.get(e.event_type, 0) + 1

    report = Report(title="VELES Maritime Intelligence Report", subtitle="Sanctions screening, evasion indicators and port activity", classification=classification, period=_period(start, end))
    data: dict[str, Any] = {"classification": classification, "period": {"start": to_iso_z(start), "end": to_iso_z(end)}, "generated_at": to_iso_z(utcnow())}

    if "executive_summary" in wanted:
        imo_exact = sum(1 for b in breaches if (b.supporting_evidence or {}).get("match_type") in ("imo", "mmsi"))
        summary = (
            f"During the reporting period VELES tracked {tracked:,} vessels ({active:,} active in the last 24 hours) and recorded "
            f"{len(breaches)} sanctions match(es) - {imo_exact} on IMO/MMSI identity - {len(evasion)} evasion indicator(s), "
            f"{len(sts)} ship-to-ship rendezvous candidate(s), {len(calls)} call(s) at sanctioned or high-risk facilities and {len(lanes)} monitored-zone event(s)."
        )
        items = [("Vessels tracked / active 24h", f"{tracked:,} / {active:,}"), ("Sanctions matches", f"{len(breaches)} ({', '.join(f'{k}: {v}' for k, v in by_authority.items()) or 'none'})"),
                 ("By severity", ", ".join(f"{k}: {v}" for k, v in by_severity.items()) or "none"), ("Evasion indicators", ", ".join(f"{k}: {v}" for k, v in evasion_by_type.items()) or "none"),
                 ("Ship-to-ship candidates", len(sts)), ("High-risk port calls", len(calls)), ("Zone / chokepoint events", len(lanes))]
        report.sections.append(Section("Executive summary", text=summary, items=items))
        data["executive_summary"] = {"text": summary, "tracked": tracked, "active_24h": active, "breaches": len(breaches), "by_authority": by_authority, "by_severity": by_severity, "evasion": evasion_by_type, "transshipments": len(sts), "high_risk_port_calls": len(calls), "zone_events": len(lanes)}

    if "breach_analysis" in wanted:
        rows = [["Vessel", "Flag", "IMO", "Authority", "Match", "Designated entity", "Conf.", "Status"]]
        rows += [[b.vessel_name, b.flag, b.imo, b.sanctioning_authority, (b.supporting_evidence or {}).get("match_type", b.breach_type), b.sanctioned_entity_name[:40], b.match_confidence, b.investigation_status] for b in breaches[:60]]
        report.sections.append(Section("Breach analysis", text=f"{len(breaches)} match(es), highest confidence first. IMO/MMSI matches identify the designated hull regardless of renaming; name-only matches carry the lower confidence shown.", table=rows, column_widths=[30, 10, 16, 14, 16, 46, 12, 20]))
        data["breaches"] = [{"vessel": b.vessel_name, "mmsi": b.mmsi, "imo": b.imo, "flag": b.flag, "authority": b.sanctioning_authority, "entity": b.sanctioned_entity_name, "match_type": (b.supporting_evidence or {}).get("match_type"), "confidence": b.match_confidence, "severity": b.severity, "status": b.investigation_status, "detected_at": to_iso_z(b.timestamp)} for b in breaches]

    if "vessel_profiles" in wanted:
        rows = [["Vessel", "MMSI", "IMO", "Flag", "Type", "Status", "Risk", "Last seen", "Last port"]]
        rows += [[v.name, v.mmsi, v.imo, v.flag_state, v.ship_type, v.sanctioned_status, v.risk_score, v.last_ais_update, v.last_port_name] for v in top_vessels]
        report.sections.append(Section("Highest-risk vessels", table=rows, column_widths=[30, 20, 16, 10, 20, 20, 10, 26, 24]))
        data["top_vessels"] = [{"name": v.name, "mmsi": v.mmsi, "imo": v.imo, "flag": v.flag_state, "risk_score": v.risk_score, "status": v.sanctioned_status} for v in top_vessels]

    if "evasion" in wanted:
        rows = [["When", "Vessel", "Indicator", "Severity", "Summary"]]
        rows += [[e.timestamp, e.vessel.name if e.vessel else e.mmsi, e.event_type, e.severity, (e.summary or "")[:110]] for e in evasion[:40]]
        report.sections.append(Section("Evasion indicators", table=rows, column_widths=[26, 30, 22, 16, 82]))
        data["evasion"] = [{"timestamp": to_iso_z(e.timestamp), "mmsi": e.mmsi, "type": e.event_type, "severity": e.severity, "summary": e.summary} for e in evasion]

    if "transshipment" in wanted:
        rows = [["When", "Vessel A", "Vessel B", "Distance", "Duration", "Conf.", "Status"]]
        rows += [[t.timestamp, t.vessel_a.name if t.vessel_a else t.vessel_a_mmsi, t.vessel_b.name if t.vessel_b else t.vessel_b_mmsi, f"{t.proximity_meters or 0:.0f} m", f"{t.duration_minutes or 0} min", t.confidence_score, t.investigation_status] for t in sts[:40]]
        report.sections.append(Section("Ship-to-ship rendezvous", table=rows, column_widths=[26, 34, 34, 18, 18, 12, 22]))
        data["transshipments"] = [{"timestamp": to_iso_z(t.timestamp), "vessel_a": t.vessel_a_mmsi, "vessel_b": t.vessel_b_mmsi, "duration_minutes": t.duration_minutes, "confidence": t.confidence_score, "status": t.investigation_status} for t in sts]

    if "port_activity" in wanted:
        rows = [["Arrived", "Vessel", "Flag", "Port", "Risk", "Dwell", "Flags"]]
        rows += [[c.arrival_time, c.vessel.name if c.vessel else c.mmsi, c.vessel.flag_state if c.vessel else "", f"{c.port_name} ({c.port_country})", c.facility_risk_level, f"{c.dwell_time_hours:.1f} h" if c.dwell_time_hours else "in port", ", ".join(c.flags_raised or [])] for c in calls[:50]]
        report.sections.append(Section("Calls at sanctioned / high-risk facilities", table=rows, column_widths=[26, 30, 10, 36, 14, 16, 44]))
        data["port_calls"] = [{"arrival": to_iso_z(c.arrival_time), "mmsi": c.mmsi, "port": c.port_name, "country": c.port_country, "risk_level": c.facility_risk_level, "dwell_hours": c.dwell_time_hours, "flags": c.flags_raised} for c in calls]

    if "zone_activity" in wanted:
        rows = [["When", "Vessel", "Zone / lane", "Context", "Severity"]]
        rows += [[z.timestamp, z.mmsi, z.lane_name, z.context, z.severity] for z in lanes[:50]]
        report.sections.append(Section("Monitored zones and chokepoints", table=rows, column_widths=[26, 24, 60, 30, 16]))
        data["zone_events"] = [{"timestamp": to_iso_z(z.timestamp), "mmsi": z.mmsi, "zone": z.lane_name, "context": z.context, "severity": z.severity} for z in lanes]

    if "audit_entries" in wanted:
        rows = [["#", "Timestamp", "Action", "Operator", "Rationale"]]
        rows += [[a.id, a.timestamp, a.action_type, a.user_id, (a.rationale or "")[:120]] for a in audit]
        report.sections.append(Section("Audit trail (most recent)", text="Entries are append-only; the database rejects modification.", table=rows, column_widths=[12, 28, 30, 20, 86], page_break_before=True))
        data["audit_entries"] = [{"id": a.id, "timestamp": to_iso_z(a.timestamp), "action": a.action_type, "user": a.user_id, "rationale": a.rationale} for a in audit]

    if "recommendations" in wanted:
        recs = _maritime_recommendations(breaches, evasion, sts, calls)
        report.sections.append(Section("Recommendations", text=" ".join(f"({i + 1}) {r}" for i, r in enumerate(recs))))
        data["recommendations"] = recs
    return report, data


def _maritime_recommendations(breaches, evasion, sts, calls) -> list[str]:
    recs = []
    identity = [b for b in breaches if (b.supporting_evidence or {}).get("match_type") in ("imo", "mmsi") and b.investigation_status not in ("cleared",)]
    if identity:
        recs.append(f"Escalate the {len(identity)} IMO/MMSI-identity match(es) ({', '.join(sorted({b.vessel_name for b in identity})[:6])}): the designated hull is transmitting under its current name.")
    review = [b for b in breaches if b.investigation_status == "review"]
    if review:
        recs.append(f"Work the review queue ({len(review)} name-only match(es)); confirm or clear using IMO numbers from a registry source.")
    dark = [e for e in evasion if e.event_type in ("ais_gap", "dark_in_zone") and e.severity in ("high", "critical")]
    if dark:
        recs.append(f"Task imagery/other collection on the {len(dark)} vessel(s) with high-severity AIS gaps near monitored zones.")
    if sts:
        recs.append(f"Cross-check the {len(sts)} rendezvous candidate(s) against cargo declarations and draught changes.")
    renamed = [e for e in evasion if e.event_type in ("name_change", "flag_change", "identity_conflict")]
    if renamed:
        recs.append(f"Re-screen the {len(renamed)} vessel(s) that changed name, flag or MMSI - re-registration is a common evasion step.")
    if calls:
        recs.append(f"Review ownership chains for vessels calling at sanctioned facilities ({len(calls)} call(s)).")
    if not recs:
        recs.append("No actionable indicators in the period; maintain routine monitoring.")
    return recs


# ----------------------------------------------------------------- sanctions
def sanctions_report_from(report_data: dict[str, Any], classification: str = "UNCLASSIFIED") -> Report:
    updates = report_data.get("updates", [])
    period = f"last {report_data.get('period_days')} day(s)"
    report = Report(title="VELES Sanctions Activity Report", subtitle="OFAC SDN, EU consolidated list and UN Security Council designations", classification=classification, period=period)
    active = report_data.get("active_listings", {})
    vessels = report_data.get("active_vessels", {})
    summary = report_data.get("summary", {})
    items = [(f"{auth} active listings", f"{active.get(auth, 0):,} ({vessels.get(auth, 0)} vessels)") for auth in ("OFAC", "EU", "UN")]
    items.append(("Updates in period", report_data.get("total_updates", 0)))
    text = "; ".join(f"{auth}: " + ", ".join(f"{k} {v}" for k, v in kinds.items()) for auth, kinds in summary.items()) or "No list changes recorded in the period."
    report.sections.append(Section("Executive summary", text=text, items=items))
    for kind, title in (("new_designation", "New designations"), ("relisted", "Relisted"), ("delisting", "Delistings"), ("program_change", "Programme changes"), ("name_change", "Name changes")):
        rows = [u for u in updates if u.get("type") == kind]
        if not rows:
            continue
        table = [["When", "Authority", "Entity", "Type", "Programmes / detail"]]
        for u in rows[:80]:
            detail = (u.get("new") or {}).get("programs") or (u.get("new") or {}).get("name") or (u.get("previous") or {}).get("status") or ""
            table.append([u.get("timestamp"), u.get("authority"), (u.get("entity_name") or "")[:60], u.get("entity_type"), detail])
        report.sections.append(Section(f"{title} ({len(rows)})", table=table, column_widths=[26, 16, 60, 18, 56]))
    return report


# -------------------------------------------------------------------- market
def market_report(db: Session, start: datetime, end: datetime, classification: str = "UNCLASSIFIED") -> tuple[Report, dict[str, Any]]:
    alerts = db.execute(select(MarketAlert).where(MarketAlert.timestamp.between(start, end)).order_by(MarketAlert.timestamp.desc())).scalars().all()
    coordination = db.execute(select(CoordinationEvent).where(CoordinationEvent.detected_at.between(start, end)).order_by(CoordinationEvent.confidence_score.desc())).scalars().all()
    latest = select(MarketCandle.asset, MarketCandle.exchange, func.max(MarketCandle.timestamp).label("ts")).group_by(MarketCandle.asset, MarketCandle.exchange).subquery()
    prices = db.execute(select(MarketCandle).join(latest, (MarketCandle.asset == latest.c.asset) & (MarketCandle.exchange == latest.c.exchange) & (MarketCandle.timestamp == latest.c.ts)).order_by(MarketCandle.asset, MarketCandle.exchange)).scalars().all()
    by_type: dict[str, int] = {}
    by_severity: dict[str, int] = {}
    for a in alerts:
        by_type[a.alert_type] = by_type.get(a.alert_type, 0) + 1
        by_severity[a.severity] = by_severity.get(a.severity, 0) + 1

    report = Report(title="VELES Market Intelligence Brief", subtitle="Multi-exchange surveillance: anomalies, coordination and liquidations", classification=classification, period=_period(start, end))
    text = f"{len(alerts)} alert(s) in the period ({', '.join(f'{k}: {v}' for k, v in by_type.items()) or 'none'}); {len(coordination)} cross-exchange coordination event(s)."
    report.sections.append(Section("Executive summary", text=text, items=[("Alerts by severity", ", ".join(f"{k}: {v}" for k, v in by_severity.items()) or "none"), ("Coordination events", len(coordination)), ("Assets monitored", ", ".join(sorted({p.asset for p in prices})) or "none")]))
    report.sections.append(Section("Latest prices", table=[["Asset", "Exchange", "Close", "Volume (USD)", "Candle time"]] + [[p.asset, p.exchange, p.close, p.volume_usd, p.timestamp] for p in prices], column_widths=[24, 28, 30, 40, 40]))
    report.sections.append(Section("Alerts", table=[["When", "Asset", "Type", "Severity", "Exchanges", "Change %", "Conf.", "Summary"]] + [[a.timestamp, a.asset, a.alert_type, a.severity, ", ".join(a.exchanges_involved or []), a.price_change_percent, a.confidence_score, (a.summary or "")[:70]] for a in alerts[:60]], column_widths=[24, 12, 20, 14, 24, 14, 10, 62]))
    report.sections.append(Section("Cross-exchange coordination", table=[["When", "Asset", "Exchanges", "Move %", "Delta (s)", "Conf.", "Status"]] + [[c.detected_at, c.asset, ", ".join(c.exchanges or []), c.correlated_price_move, c.time_delta_seconds, c.confidence_score, c.investigation_status] for c in coordination[:40]], column_widths=[26, 14, 40, 18, 18, 12, 24]))
    data = {
        "classification": classification, "period": {"start": to_iso_z(start), "end": to_iso_z(end)}, "generated_at": to_iso_z(utcnow()),
        "summary": {"alerts": len(alerts), "by_type": by_type, "by_severity": by_severity, "coordination_events": len(coordination)},
        "prices": [{"asset": p.asset, "exchange": p.exchange, "close": p.close, "volume_usd": p.volume_usd, "timestamp": to_iso_z(p.timestamp)} for p in prices],
        "alerts": [{"timestamp": to_iso_z(a.timestamp), "asset": a.asset, "type": a.alert_type, "severity": a.severity, "exchanges": a.exchanges_involved, "change_percent": a.price_change_percent, "confidence": a.confidence_score, "summary": a.summary, "acknowledged": a.acknowledged} for a in alerts],
        "coordination": [{"detected_at": to_iso_z(c.detected_at), "asset": c.asset, "exchanges": c.exchanges, "move_percent": c.correlated_price_move, "confidence": c.confidence_score, "status": c.investigation_status, "summary": c.summary} for c in coordination],
    }
    return report, data
