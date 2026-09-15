# VELES User Guide

A walkthrough of the dashboard for analysts. Everything on screen is also
available from the API (`/docs`) and in PDF/JSON/CSV exports.

## Reading the marking

The green/blue/red bar at the top and bottom of every page is the
classification marking (`classification.banner` in Settings). Reports carry
the same marking.

## Dashboard

Live tiles: vessels tracked (with the AIS sources feeding them), open sanctions
breaches, unacknowledged market alerts, backend health. Below: the top
sanctions matches, pending market alerts, recent significant events from the
audit log, and one-click PDF reports (maritime 7 d, sanctions 7 d, market 7 d).

## Maritime

**Map** - every vessel heard in the last 6 hours. Green = clear, orange =
flagged (low-confidence match, in the review queue), red = breach. Red `!`
markers are breach locations. Layers (top-right control): OFAC / EU / UN
monitoring zones, war and piracy zones, shipping lanes and chokepoints, ports.
Click a vessel for its popup and *View details*.

**Vessels** - searchable grid (name / MMSI / IMO / owner), sortable by risk.

**Breach board** - sanctions matches. *Match* explains how the vessel matched:
`imo` / `mmsi` (the designated hull itself - strongest), `name exact`,
`name fuzzy`, `owner` / `operator` / `beneficial owner`, or `flag program`
(flagged to a comprehensively sanctioned jurisdiction). Change the status
inline: flagged -> investigating -> escalated / cleared. Clearing recomputes the
vessel's status and risk score; every change is audited. Switch the view to
*review queue* for low-confidence name matches.

**Evasion patterns** - AIS gaps (graded by whether the gap touches a monitored
zone), renames, re-flagging, identity conflicts (an IMO reappearing under a
different MMSI), dark flagged vessels, and *position anomalies* - physically
impossible reports (a ship inland, 40 knots) that point at GNSS spoofing or a
manipulated transponder.

**Transshipment** - pairs of slow cargo vessels within the proximity threshold,
away from ports, for at least the configured duration; confidence rises with
duration, tanker involvement, zone context and the vessels' own risk.

**Port activity** - calls at sanctioned / high-risk facilities with dwell times
and flags (`sanctioned_facility`, `unusual_dwell_time`,
`flag_of_convenience_at_high_risk_port`).

**Zones & lanes** - entries into monitoring zones and chokepoint transits by
high-risk vessels.

**Vessel detail** - full profile, sanctions matches with evidence, linked
vessels, evasion indicators, port calls / STS / zone events, the track with a
replay slider, risk factors, and the vessel's audit history.

## Sanctions

Search the OFAC, EU and UN lists by name, alias, IMO or MMSI. The search also
runs an explicit screening check (written to the audit log) and shows the
confidence and the authorities involved. The updates timeline shows what
changed at each refresh (new designations, delistings, programme changes); the
programme table shows listing and vessel counts per programme. *Refresh lists*
re-downloads all three lists (about 20 s).

## Market

Per-exchange price ticker with 24 h change, a multi-exchange price chart with
alert markers, volume by exchange with spike highlighting, realised volatility
and clusters, the anomaly-alert board (acknowledge to clear) and the
cross-exchange coordination board. Alert types: `price anomaly` (3 sigma from
the rolling baseline), `volume spike` (> 2x the 24 h average in a 5-minute
window), `coordination` (synchronised move on 2+ exchanges with correlated
returns) and `liquidation` (futures liquidation cascades).

## Linkage

Pick a vessel and see everything it is connected to: shared owner / operator /
beneficial owner, the same designated entity, ship-to-ship partners, and shared
high-risk ports - each with a link strength. Declared fleets group vessels by
owner. Ownership fields come from enriched sources (AIS alone carries none).

## Audit

The immutable log of every detection, screening, review, export and
configuration change. Filter by action and operator; export JSON / CSV or a
PDF intelligence report. The database rejects updates and deletes on this
table.

## Settings

Edit thresholds, cadences, notification options and the classification marking
(saved to `settings.local.yaml`, audited). Paste the API token here if the
backend requires one. AIS source toggles take effect after a restart.

## Confidence and severity at a glance

| Confidence | Meaning |
|-----------|---------|
| 0.95 | IMO / MMSI identity match - treat as the designated vessel |
| 0.8-0.9 | Exact name match with agreeing/unknown flag |
| 0.6-0.7 | Owner/operator match, fuzzy name with agreeing flag |
| 0.4-0.55 | Review queue: name-only with a different flag, comprehensive-programme flag (IR/KP/SY/CU), beneficial-owner links |
| < 0.4 | Not shown (a differing IMO number rules a name match out) |
