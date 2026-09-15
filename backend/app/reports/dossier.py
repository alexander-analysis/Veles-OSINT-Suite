"""PDF dossiers for one hull or one listed party, rendered from the same JSON the API returns."""

from typing import Any

from app.reports.pdf import Report, Section


def _d(value: Any) -> str:
    """Date-ish strings shortened to the day, None to '-'."""
    if not value:
        return "-"
    text = str(value)
    return text[:16].replace("T", " ") if len(text) >= 16 and text[4] == "-" else text


def _pct(value: Any) -> str:
    return f"{round((value or 0) * 100)}%" if value is not None else "-"


def vessel_dossier_report(data: dict[str, Any], classification: str = "UNCLASSIFIED") -> Report:
    v = data["vessel"]
    report = Report(title=f"Vessel dossier - {v['name']} ({v.get('flag') or '?'})", subtitle=f"MMSI {v['mmsi']}{' - IMO ' + v['imo'] if v.get('imo') else ''} - {v.get('ship_type') or 'type unknown'}", classification=classification)
    facts = [("MMSI", v["mmsi"]), ("IMO", v.get("imo") or "-"), ("Flag", v.get("flag") or "-"), ("Type", v.get("ship_type") or "-"), ("Length", f"{v['length_m']:.0f} m" if v.get("length_m") else "-"), ("Draught", f"{v['draught']:.1f} m" if v.get("draught") else "-")]
    counts = {k: len(data.get(k) or []) for k in ("listings_by_imo", "port_state_control", "shipments", "dark_oil_indicators", "fusion_links", "spoofing_clusters")}
    summary = (f"{counts['listings_by_imo']} listing(s) share this hull's IMO; {counts['port_state_control']} port state control record(s); {counts['shipments']} reconstructed oil shipment(s); "
               f"{counts['dark_oil_indicators']} dark-oil indicator(s); {counts['spoofing_clusters']} GNSS spoofing cluster(s); {counts['fusion_links']} cross-domain fusion link(s).")
    report.sections.append(Section("Identity", text=summary, items=facts))
    if data.get("listings_by_imo"):
        report.sections.append(Section("Sanctions listings by IMO", table=[["Authority", "Listed name", "Programmes", "Designated", "Owner"], *[[e["authority"], e["name"][:50], ", ".join(e.get("programs") or [])[:40], _d(e.get("designation_date"))[:10], (e.get("vessel_owner") or "-")[:40]] for e in data["listings_by_imo"]]], column_widths=[20, 56, 46, 22, 46]))
    if data.get("port_state_control"):
        report.sections.append(Section("Port state control", table=[["Date", "Event", "Regime", "Port", "Deficiencies", "Company"], *[[_d(p.get("event_date"))[:10], p["event_type"], p["source"].replace("_", " "), f"{p.get('port') or '-'} ({p.get('port_country') or '?'})", p.get("deficiency_count") or 0, (p.get("company") or "-")[:36]] for p in data["port_state_control"]]], column_widths=[22, 20, 24, 50, 22, 52]))
    if data.get("shipments"):
        report.sections.append(Section("Oil shipments", table=[["Loaded", "From", "To", "Cargo", "Barrels", "Flags"], *[[_d(s.get("loading_date"))[:10], f"{s.get('loading_location') or '?'} ({s.get('origin_country') or '?'})"[:34], f"{s.get('discharge_location') or s.get('status') or '?'} ({s.get('destination_country') or '?'})"[:34], s.get("cargo_type") or "-", f"{s['cargo_volume_barrels']:,.0f}" if s.get("cargo_volume_barrels") else "-", ", ".join(k for k, on in (("sanctioned route", s.get("sanctioned_route")), ("dark oil", s.get("dark_oil_suspect"))) if on) or "-"] for s in data["shipments"]]], column_widths=[22, 48, 48, 20, 22, 30]))
    if data.get("dark_oil_indicators"):
        report.sections.append(Section("Dark-oil indicators", table=[["Detected", "Pattern", "Severity", "Conf.", "Summary"], *[[_d(d.get("detected_at")), (d.get("pattern") or "").replace("_", " "), d.get("severity") or "-", _pct(d.get("confidence")), (d.get("summary") or "")[:80]] for d in data["dark_oil_indicators"]]], column_widths=[28, 34, 18, 14, 96]))
    if data.get("spoofing_clusters"):
        report.sections.append(Section("GNSS spoofing / jamming clusters", table=[["When", "Severity", "Hulls", "On land", "Summary"], *[[_d(c.get("timestamp")), c.get("severity") or "-", c.get("vessel_count") or "-", "yes" if c.get("inland") else "no", (c.get("summary") or "")[:90]] for c in data["spoofing_clusters"]]], column_widths=[28, 18, 14, 16, 114]))
    if data.get("fusion_links"):
        report.sections.append(Section("Fusion links", table=[["Detected", "Type", "Conf.", "Signal A", "Signal B"], *[[_d(c.get("detected_at")), (c.get("type") or "").replace("_", " "), _pct(c.get("confidence")), (c.get("a") or "")[:60], (c.get("b") or "")[:60]] for c in data["fusion_links"][:25]]], column_widths=[26, 30, 14, 60, 60]))
    report.sections.append(Section("Method", text="Compiled from VELES's own records: AIS tracks, OFAC / EU / UN lists matched by IMO, Paris and Tokyo MoU port state control, energy-facility port calls, dark-oil pattern detection, GNSS anomaly clustering and the fusion engine. Scores are analytic prioritisation values, not findings."))
    return report


def entity_dossier_report(data: dict[str, Any], classification: str = "UNCLASSIFIED") -> Report:
    e = data["entity"]
    authorities = ", ".join(e.get("designating_authorities") or [e.get("designating_authority") or "?"])
    report = Report(title=f"Entity dossier - {e['name']}", subtitle=f"{authorities} - {e.get('entity_type') or 'entity'} - {', '.join(e.get('programs') or [])[:80]}", classification=classification)
    facts = [("Authority", authorities), ("Type", e.get("entity_type") or "-"), ("Designated", _d(e.get("designation_date"))[:10]), ("Country", e.get("country_linked") or "-"), ("Programmes", ", ".join(e.get("programs") or [])[:120] or "-"), ("Aliases", "; ".join((e.get("aliases") or [])[:6]) or "-"), ("Wallet balance", f"${data.get('wallet_balance_usd', 0):,.0f}")]
    counts = {k: len(data.get(k) or []) for k in ("other_listings", "vessels", "companies", "wallets", "transfers", "domains", "legal_events", "aircraft")}
    summary = (f"Also listed by {counts['other_listings']} other authority list(s). Linked in VELES: {counts['vessels']} vessel match(es), {counts['companies']} company record(s), {counts['wallets']} wallet(s) with {counts['transfers']} recent transfer(s), "
               f"{counts['domains']} domain(s), {counts['legal_events']} legal event(s), {counts['aircraft']} aircraft.")
    report.sections.append(Section("Listing", text=summary, items=facts))
    if e.get("remarks"):
        report.sections.append(Section("Remarks from the list", text=str(e["remarks"])[:1500]))
    if data.get("other_listings"):
        report.sections.append(Section("Other listings of the same name", table=[["Authority", "Programmes", "Designated"], *[[o["authority"], ", ".join(o.get("programs") or [])[:70], _d(o.get("designation_date"))[:10]] for o in data["other_listings"]]]))
    if data.get("vessels"):
        report.sections.append(Section("Vessels matched to this listing", table=[["Vessel", "MMSI", "IMO", "Flag", "Match", "Conf.", "Status"], *[[(b.get("vessel_name") or "")[:30], b.get("mmsi") or "-", b.get("imo") or "-", b.get("flag") or "-", (b.get("breach_type") or "").replace("_", " "), _pct(b.get("match_confidence")), b.get("status") or "-"] for b in data["vessels"]]], column_widths=[46, 24, 22, 14, 30, 14, 40]))
    if data.get("companies"):
        report.sections.append(Section("Companies", table=[["Company", "Country", "LEI", "Link", "Risk", "Flags"], *[[c["company_name"][:40], c.get("registration_country") or "-", c.get("lei") or "-", (c.get("sanctions_match_type") or "-").replace("_", " "), _pct(c.get("risk_score")), ", ".join(k for k, on in (("shell", c.get("is_shell_company")), ("opaque", c.get("ownership_opaque"))) if on) or "-"] for c in data["companies"]]], column_widths=[60, 18, 44, 26, 14, 28]))
    if data.get("ownership_chains"):
        report.sections.append(Section("Ownership chains", table=[["Subsidiary", "Ultimate owner", "Country", "Hops", "Sanctioned in chain"], *[[(ch.get("subsidiary_name") or "")[:40], (ch.get("ultimate_owner_name") or "")[:40], ch.get("ultimate_owner_country") or "-", ch.get("chain_length") or "-", "yes" if ch.get("involves_sanctioned") else "no"] for ch in data["ownership_chains"]]]))
    if data.get("wallets"):
        report.sections.append(Section("Wallets", table=[["Chain", "Address", "Balance USD", "Tx", "Last active"], *[[w["blockchain"], w["address"][:44], f"{(w.get('balance_usd') or 0):,.0f}", w.get("transaction_count") or 0, _d(w.get("last_active"))[:10]] for w in data["wallets"]]], column_widths=[20, 90, 30, 16, 26]))
    if data.get("transfers"):
        report.sections.append(Section("Recent transfers", table=[["When", "Chain", "USD", "Token", "Pattern", "Counterparty"], *[[_d(t.get("timestamp")), t["blockchain"], f"{(t.get('amount_usd') or 0):,.0f}", t.get("token") or "-", (t.get("pattern") or "-").replace("_", " "), (t.get("destination_entity") or t.get("source_entity") or "-")[:30]] for t in data["transfers"][:20]]], column_widths=[28, 20, 26, 16, 40, 60]))
    if data.get("domains"):
        report.sections.append(Section("Web infrastructure", table=[["Domain", "Live", "Hosting", "ASN org", "Registrar", "Risk"], *[[d["value"][:34], "yes" if d.get("is_live") else "no", d.get("hosting_country") or "-", (d.get("asn_org") or "-")[:26], (d.get("registrar") or "-")[:24], _pct(d.get("risk_score"))] for d in data["domains"]]], column_widths=[52, 14, 20, 44, 44, 16]))
    if data.get("legal_events"):
        report.sections.append(Section("Legal and enforcement", table=[["Date", "Source", "Type", "Title", "Penalty USD"], *[[_d(ev.get("event_date"))[:10], ev["source"].replace("_", " "), ev.get("event_type") or "-", ev["title"][:70], f"{ev['penalty_usd']:,.0f}" if ev.get("penalty_usd") else "-"] for ev in data["legal_events"]]], column_widths=[22, 28, 24, 90, 26]))
    if data.get("aircraft"):
        report.sections.append(Section("Aircraft", table=[["Registration", "Model", "Operator", "Sightings", "Last seen"], *[[a["registration"], a.get("model") or "-", (a.get("operator") or "-")[:36], a.get("sightings_count") or 0, _d(a.get("last_seen"))] for a in data["aircraft"]]]))
    report.sections.append(Section("Method", text="Compiled from VELES's own records: the consolidated OFAC / EU / UN lists, AIS matches, GLEIF ownership walks, public blockchain explorers, RDAP / certificate transparency, court and enforcement feeds and ADS-B. Scores are analytic prioritisation values, not findings."))
    return report
