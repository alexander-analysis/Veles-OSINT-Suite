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
duration, tanker involvement, zone context and the vessels' own risk. Marina
and anchorage noise is filtered: a pair needs at least one typed tanker or
cargo hull, inside a crowded cluster (`transshipment_cluster_limit` slow
vessels within ~6 km) it needs a tanker, moored hulls and fishing boats never
pair, and a contact that stays continuous beyond
`transshipment_max_duration_hours` is dismissed as a berthed or laid-up pair.

**Port activity** - calls at sanctioned / high-risk facilities with dwell times
and flags (`sanctioned_facility`, `unusual_dwell_time`,
`flag_of_convenience_at_high_risk_port`).

**Zones & lanes** - entries into monitoring zones and chokepoint transits by
high-risk vessels.

**Vessel detail** - full profile, sanctions matches with evidence, linked
vessels, evasion indicators, port calls / STS / zone events, the track with a
replay slider, risk factors, and the vessel's audit history. The *cross-domain
dossier* card pulls in what the other bots hold on the same hull: listings
sharing its IMO (with a link to the entity dossier), port state control
detentions and bans, oil shipments and dark-oil indicators, and fusion links
that name the vessel.

## Sanctions

Search the OFAC, EU and UN lists by name, alias, IMO or MMSI. The search also
runs an explicit screening check (written to the audit log) and shows the
confidence and the authorities involved. The updates timeline shows what
changed at each refresh (new designations, delistings, programme changes); the
programme table shows listing and vessel counts per programme. *Refresh lists*
re-downloads all three lists (about 20 s).

**Entity dossier** - the *dossier* button on a search result (or a
`/sanctions?entity=ID` link from a vessel page) compiles everything the
platform has attached to that listing: the same name on other authorities'
lists, matched vessels, companies and ownership chains, wallets with balance
and recent transfers, domains, legal events and aircraft. An empty dossier only
means no bot has linked a record yet.

## Market

Per-exchange price ticker with 24 h change, a multi-exchange price chart with
alert markers, volume by exchange with spike highlighting, realised volatility
and clusters, the anomaly-alert board (acknowledge to clear) and the
cross-exchange coordination board. Alert types: `price anomaly` (3 sigma from
the rolling baseline), `volume spike` (> 2x the 24 h average in a 5-minute
window), `coordination` (synchronised move on 2+ exchanges with correlated
returns) and `liquidation` (futures liquidation cascades).

## Geopolitical

GDELT events (every 15 minutes), GDELT article searches, UK FCDO / UN / OFAC
announcements and topic-filtered state-media headlines, classified as conflict,
sanctions, maritime incident, port closure, infrastructure, trade or political.
The map shows geocoded events (colour = type, size = severity); the list can be
narrowed by window, severity, country, free text and "linked only" (events the
engine tied to a market alert, sanctions match, evasion event, STS rendezvous or
list change). Confirm or dispute an event in the detail panel - both are audited.

## Blockchain

Every OFAC "Digital Currency Address" is a watched wallet. The table shows
balances (including USDT on Tron), transaction counts and last activity;
"Transfers" lists movements scored as sanctioned counterparty, exchange
cash-out, mixer use or whale transfer. The live feeds badge shows the Bitcoin
mempool stream and the last Ethereum block scanned. Add your own address to the
watch list with the form (audited).

## Corporate

Listed companies and vessel owners are resolved through GLEIF in rotation.
"Sanctions exposure" lists companies that are not listed themselves but sit
directly under (or above) a listed party - the starting point for 50 %-rule
work. Shell / opaque views surface secrecy jurisdictions, undisclosed parents,
lapsed registrations and fresh formations. The live search queries GLEIF; an
"import + walk" pulls the LEI with its parents and subsidiaries.

## Energy

Curated terminals, refineries, LNG plants and STS anchorages. Tanker calls with
draught changes become shipments (origin, destination, estimated barrels);
dark-oil indicators flag loadings at sanctioned facilities, AIS gaps and
spoofing after loading, STS transfers, anchorage loitering and identity changes.
Mark an indicator "investigating" or "clear" from the list (audited). The chart
compares laden departures from sanctioned facilities with Brent / WTI.

## Fusion

One queue for every bot's output, ranked by severity and correlation count.
"Composite alerts" appear when signals from three or more domains share a
vessel, listed party, wallet, company, facility, aircraft or domain inside the
window; each carries a narrative summary and can be acknowledged. The
"Cross-domain brief 24h (PDF)" button on the dashboard renders the same
material as a report.

## Monitors

Tier 2 / 3 collectors: sanctioned aircraft on ADS-B (map + track per airframe),
port state control detentions and bans (Paris and Tokyo MoU) joined to the vessels
VELES tracks - a detention on a flagged hull is highlighted and raises its risk score,
ransomware and breach postings matched to tracked companies and critical
sectors, state-media narratives (state-only / amplified / mirrored against
official coverage), the web infrastructure of listed parties (whether a domain
still resolves and where it is hosted) and enforcement / prosecution / docket
records naming listed parties.

## Satellite overlay

On the maritime map, the layer control offers NASA GIBS MODIS true-colour
imagery and thermal anomalies for the previous day - useful context for fires
at terminals, ice conditions and cloud cover over an area of interest.

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
