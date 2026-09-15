# VELES API Reference

Base URL: `http://<host>:8000` (or through Nginx on port 80). Interactive
docs: `/docs` (Swagger UI) and `/redoc`. All timestamps are UTC ISO-8601 with
a `Z` suffix.

**Authentication**: open by default. When `VELES_API_TOKEN` is set in
`backend/.env`, every `/api/*` call except `/api/health` must send
`X-API-Key: <token>` (or `Authorization: Bearer <token>`; WebSocket clients
use `?access_token=<token>`); otherwise **401**.

## Health

### `GET /api/health`

Liveness plus freshness indicators. Returns **503** with the same body when
the database is unreachable.

```json
{
  "status": "ok",
  "version": "0.1.0",
  "environment": "development",
  "timestamp": "2026-09-14T21:58:01Z",
  "uptime_seconds": 12.4,
  "database": { "ok": true, "dialect": "sqlite", "size_bytes": 914648, "error": null },
  "scheduler": { "enabled": true, "running": true, "jobs": [ { "id": "heartbeat", "next_run_time": "2026-09-14T22:02:49Z" } ] },
  "last_market_update": null,
  "last_ais_update": null
}
```

## Market (`/api/market`)

| Endpoint | Purpose |
|----------|---------|
| `GET /prices?assets=BTC,ETH&exchanges=binance,kraken` | Latest price per (asset, exchange) with `24h_change_percent`, `volume_24h_usd`, `signal_quality` (freshness 0-100) |
| `GET /alerts?severity=high,critical&asset=BTC&alert_type=price_anomaly&acknowledged=false&hours=24&limit=50&offset=0` | Anomaly alerts (`price_anomaly`, `volume_spike`, `coordination`, `liquidation`) with `intelligence_summary` and `confidence_score` |
| `POST /alerts/{id}/acknowledge` `{"acknowledged_by": "...", "notes": "..."}` | Acknowledge an alert (audited) |
| `GET /coordination?asset=BTC&status=flagged&min_confidence=0.6` | Cross-exchange coordination events with `analyst_assessment` |
| `PATCH /coordination/{id}` `{"investigation_status": "investigating", "analyst_notes": "..."}` | Update investigation status / notes (audited) |
| `GET /history/{asset}?hours=6&timeframe=1m&exchanges=binance,kraken` | Candles pivoted by exchange + `composite`; `timeframe` in `1m,5m,15m,1h,4h,1d` is resampled server-side; includes `anomalies_in_period` |
| `GET /volatility/{asset}?hours=24&window_minutes=15` | Realised volatility per exchange (daily / annualised), `clusters` of sustained high volatility, rolling `series` |
| `POST /config` `{"assets": ["BTC","ETH","SOL"], "price_anomaly_sigma": 2.5}` | Patch the `market` section of the configuration (audited; bots pick it up on their next run) |
| `GET /export/{24h|7d|30d}?format=json|pdf|csv&classification=` | Market intelligence brief (audited export) |
| `GET /status` | Bot runtime: last fetch, per-pair counts, candles stored, open alerts, liquidation stream state |

Alert `severity` is derived from magnitude: price anomalies by sigma
(3/4/5/7), volume spikes by multiplier (2/3/5/10), liquidation cascades by
total notional ($1M/$5M/$20M/$100M), coordination by confidence.

## Maritime (`/api/maritime`)

| Endpoint | Purpose |
|----------|---------|
| `GET /vessels?bbox=-180,-90,180,90&risk_filter=all|flagged|breach&max_age_hours=24` | GeoJSON FeatureCollection of current positions (`marker_color`: clear `#2ecc71`, flagged `#f39c12`, breach `#e74c3c`) |
| `GET /vessels/table?q=&flag=&status=&min_risk=&sort=risk|recent|name&limit=&offset=` | Searchable vessel grid |
| `GET /vessel/{mmsi}` | Full profile: identity + history, sanctions matches, port history, evasion events, transshipments, zone events, position timeline, correlated vessels, audit history, risk factors |
| `GET /vessel/{mmsi}/dossier` | Cross-domain dossier for one hull: listings sharing its IMO, port state control events, oil shipments, dark-oil indicators, fusion links naming the vessel |
| `GET /vessel-correlation/{mmsi}?days=30` | Linked vessels (shared owner/operator/beneficial owner, shared designated entity, STS partners, shared high-risk ports) with link strength |
| `GET /fleets?min_size=2` | Vessel groups sharing a declared owner/operator |
| `GET /breaches?authority=&severity=&status=&breach_type=&min_confidence=` | Sanctions matches; `status` defaults to open (`flagged,investigating,escalated`), use `review` for the low-confidence queue or `all` |
| `GET /breaches/{authority}` | All matches for OFAC / EU / UN |
| `PATCH /breach/{id}` `{"investigation_status": "investigating|cleared|escalated", "analyst_notes": "..."}` | Audited status change; clearing recomputes the vessel status and risk |
| `GET /evasion-patterns?event_type=&severity=&hours=` / `PATCH /evasion-patterns/{id}` | AIS gaps, renames, re-flagging, IMO conflicts, dark vessels, `position_anomaly` (impossible speed/jump - spoofing), `spoofing_cluster` (3+ hulls with implausible positions in one ~11 km cell; `details.vessels` lists them) |
| `GET /transshipment?hours=&min_confidence=` / `PATCH /transshipment/{id}` | Ship-to-ship rendezvous candidates |
| `GET /port-calls?hours=&port=&risk=&only_flagged=&open_only=` and `GET /port-calls/{24h|7d|30d}` | Port calls with dwell times and flags (`sanctioned_facility`, `unusual_dwell_time`, ...) plus per-port totals |
| `GET /ports` | Curated port reference as GeoJSON |
| `GET /sanctions-zones` | Monitoring zones as GeoJSON, grouped `ofac` / `eu` / `un` / `other` / `all` |
| `GET /shipping-lanes` / `GET /shipping-lanes/violations?hours=&context=` | Lanes/chokepoints GeoJSON; zone entries and chokepoint transits by high-risk vessels |
| `GET /audit-log?start_date=&end_date=&action_type=&vessel_id=&user=&limit=&offset=` | Immutable compliance log; `GET /audit-log/actions` lists action types |
| `POST /audit-log/export` `{"format": "json|csv|pdf", "start_date": ..., "include_sections": [...], "classification": "CONFIDENTIAL"}` | Export (audited): JSON/CSV of entries, or the PDF intelligence report |
| `GET /report?days=7&format=json|pdf&classification=&sections=` | Maritime intelligence report: executive summary, breach analysis, highest-risk vessels, evasion, STS, port activity, zone events, audit trail, recommendations |
| `GET /status` | Bot status: sources, source errors (missing keys), last poll, counts, stream clients |
| `WS /stream` | Frames: `hello`, `vessel_positions` (batched after every poll), `breach_detected`, `transshipment_detected` |

## Sanctions (`/api/sanctions`)

| Endpoint | Purpose |
|----------|---------|
| `GET /entities?query=&type=&authority=&program=&active=&limit=&offset=` | Search listings by name / alias / IMO / MMSI with cross-authority `designating_authorities` |
| `GET /entities/{id}` | One listing |
| `GET /entities/{id}/dossier` | Everything held on one listed party: other authorities' listings of the same name, matched vessels, companies + ownership chains, wallets (+ balance, recent transfers), domains, legal events, aircraft |
| `POST /check-entity` `{"entity_name": "...", "entity_type": "company", "min_similarity": 0.85}` | Screen a name (audited as `sanctions_check`) |
| `GET /vessel/{mmsi}` | Recorded breaches + live screen + recommendation |
| `GET /updates?timeframe=7&authority=&type=` | Change log since the last refreshes with per-authority summary |
| `GET /programs?authority=` | Programme counts |
| `GET /report/{7days|30days|24h}?format=json|pdf` | Activity report (JSON or PDF) |
| `GET /status` / `POST /refresh?authority=OFAC,EU` | Bot status; trigger a refresh (202) |

## Geopolitical (`/api/geopolitical`)

| Endpoint | Purpose |
|----------|---------|
| `GET /events?hours=&event_type=&country=&min_severity=&source=&correlated=&q=&limit=&offset=` | Events (types: conflict, sanctions, political, trade, port_closure, infrastructure, maritime_incident); `country` matches primary, secondary or affected countries |
| `GET /events/{id}` | One event with its cross-domain correlations |
| `POST /events/{id}/verify` `{"status": "confirmed|disputed|unconfirmed", "notes": "...", "analyst": "..."}` | Analyst verification (audited as `event_verification`) |
| `GET /alerts?hours=&limit=` | High / critical events, correlated ones first |
| `GET /correlations?hours=&alert_type=&min_score=` | Event <-> market alert / sanctions breach / evasion event / STS / sanctions update links |
| `GET /timeline/{ISO2}?days=` | Per-country daily buckets + events |
| `GET /geojson?hours=&min_severity=` | Geolocated events as a FeatureCollection (GDELT action geography) |
| `GET /summary?hours=` | Counts by type / severity / country for dashboards |
| `GET /sources` | Feed health (last fetch, status, latency) |
| `GET /status` / `POST /refresh?job=all|gdelt|doc|feeds|correlate` | Bot status; run a collection job now (202) |

## Blockchain (`/api/blockchain`)

| Endpoint | Purpose |
|----------|---------|
| `GET /wallets?chain=&wallet_type=&sanctioned=&active_hours=&q=&min_balance_usd=&sort=balance|last_active|risk|owner&limit=&offset=` | Tracked wallets (OFAC digital-currency addresses, curated exchange / mixer labels, analyst additions) |
| `GET /wallets/{chain}/{address}` | Wallet + its recorded transfers, co-spend cluster and explorer link |
| `POST /wallets` `{"blockchain": "ethereum", "address": "0x...", "label": "...", "wallet_type": "individual", "watch": true}` | Add an address to the watch list (audited as `wallet_watch_added`) |
| `GET /transactions?hours=&chain=&pattern=&involves_sanctioned=&involves_mixer=&min_usd=&address=` | Recorded transfers (patterns: sanctioned_counterparty, exchange_cashout, exchange_withdrawal_to_sanctioned, sanctioned_mixer_usage, mixer_usage, whale_transfer) |
| `GET /whales?hours=` | Largest whale transfers |
| `POST /transactions/{id}/acknowledge?analyst=` | Acknowledge a flagged transfer (audited) |
| `GET /clusters` | Bitcoin common-input-ownership clusters seeded from sanctioned addresses |
| `GET /summary?hours=` | Wallet counts by chain, balance held in sanctioned wallets, flagged / whale counts, prices, stream state |
| `GET /status` / `POST /refresh?job=all|sync|prices|poll|scan` | Bot status; run a job now (202) |

## Corporate (`/api/corporate`)

| Endpoint | Purpose |
|----------|---------|
| `GET /companies?q=&country=&linked=&match_type=&exposure_only=&shell=&opaque=&has_lei=&origin=&min_risk=&sort=risk|name|updated|enriched` | Tracked companies (sanctions seeds, vessel owners, ownership-walk discoveries, analyst imports) |
| `GET /companies/{id}` | Company + shareholders / parents, subsidiaries, officers, ownership chain, the listing it is tied to, GLEIF link |
| `GET /exposure` | Companies not listed themselves but directly under / above a listed party (`parent`, `ultimate_parent`, `child` match types) |
| `GET /chains?sanctioned_only=` | Ownership chains with risk scores |
| `GET /search?q=&live=true` | Live GLEIF search; each hit shows whether it is tracked and whether the name screens against the lists |
| `POST /ingest` `{"lei": "...", "analyst": "..."}` | Import an LEI with parents / subsidiaries on the bot loop (audited as `company_lookup`) |
| `GET /summary` | Counts: tracked, resolved, exposure, shells, chains, top countries |
| `GET /status` / `POST /refresh?job=all|seed|enrich` | Bot status; run seeding / a GLEIF batch now (202) |

## Energy (`/api/energy`)

| Endpoint | Purpose |
|----------|---------|
| `GET /facilities?country=&facility_type=&sanctioned=` / `GET /facilities/geojson` | Curated terminals, refineries, LNG plants and STS anchorages with 7 / 30-day tanker-call counters |
| `GET /facilities/{id}?days=` | Facility detail: recent tanker calls (draught in / out), shipments, daily flow snapshots |
| `GET /shipments?days=&sanctioned_only=&dark_oil_only=&origin=&destination=&status=&mmsi=` | Tanker voyages reconstructed from facility calls (laden departure -> next call) |
| `GET /dark-oil?days=&pattern=&min_confidence=&status=` | Dark-oil indicators (sanctioned_loading, sanctioned_vessel_loading, ais_gap_after_loading, sts_transfer, sts_hub_loitering, spoofed_position, identity_change, discharge_to_sanctioned_destination) |
| `POST /dark-oil/{id}/status?status=investigating|confirmed|cleared&analyst=&notes=` | Investigation workflow (audited) |
| `GET /flows?days=&facility_id=&country=&sanctioned_only=` | Daily per-facility arrivals / departures / laden departures / estimated barrels / flagged tankers |
| `GET /price-context?days=` | Laden departures from sanctioned facilities against Brent (fallback WTI) daily closes with a Pearson correlation |
| `GET /summary?days=` | Counters, indicator mix, most active facilities, origin -> destination countries |
| `GET /status` / `POST /refresh?job=all|facilities|visits|shipments|dark_oil|snapshots` | Bot status; run a job now (202) |

## Fusion (`/api/fusion`)

| Endpoint | Purpose |
|----------|---------|
| `GET /queue?hours=&min_severity=&domains=&limit=` | Every signal from every bot in one ranked list (severity, correlation count, recency) with its typed keys |
| `GET /composite-alerts?hours=&acknowledged=&min_severity=` / `GET /composite-alerts/{id}` | Clusters of correlated signals spanning >= 3 bot domains, with a narrative summary |
| `POST /composite-alerts/{id}/acknowledge?analyst=&notes=` | Acknowledge (audited) |
| `GET /correlations?hours=&correlation_type=&signal_type=&min_confidence=` | Pairwise cross-domain correlations (shared vessel / listed party / wallet / company / facility / country / asset) |
| `GET /timeline?hours=&bucket_hours=` | Signal counts per bucket per domain |
| `GET /summary?hours=` | Open / critical composite alerts, correlation counts by type, top alerts |
| `GET /brief?hours=&format=json|pdf&classification=` | Cross-domain intelligence brief covering every bot (composite alerts, maritime, energy, geopolitical, market, blockchain, corporate, aviation, cyber, information, legal) |
| `GET /status` / `POST /refresh` | Engine status; run a correlation pass now (202) |

## Monitors (tier 2 / 3)

| Endpoint | Purpose |
|----------|---------|
| `GET /api/aviation/aircraft?seen_days=&operator=&country=&q=` / `GET /api/aviation/aircraft/{id}/sightings` / `GET /api/aviation/sightings` / `GET /api/aviation/geojson` | Listed airframes (OFAC aircraft listings), their ADS-B sightings and last positions |
| `POST /api/aviation/aircraft` `{"registration": "...", "icao_hex": "...", "operator": "..."}` | Watch an extra airframe (audited) |
| `GET /api/aviation/summary` / `GET /status` / `POST /refresh?job=all|sync|sweep|hexes` | Status and jobs |
| `GET /api/leaks/events?days=&relevance=&min_score=&source=&q=` / `GET /summary` / `POST /refresh` | Ransomware victims and breaches matched against tracked companies, listings, sectors, keywords |
| `GET /api/narratives/?days=&divergence=&min_score=` / `GET /summary` / `POST /refresh` | State-media narrative clusters (state_only / amplified / mirrored) |
| `GET /api/infra/assets?live=&country=&q=&checked=&min_risk=` / `GET /summary` / `POST /refresh?job=all|seed|footprint` | Domains from OFAC "Website" remarks: registration, resolution, hosting, certificate estate, findings |
| `GET /api/legal/events?days=&source=&event_type=&matched_only=&q=` / `GET /summary` / `POST /refresh?job=all|official|dockets` | OFAC penalties, DOJ releases, CourtListener dockets naming listed parties |
| `GET /api/psc/events?days=&event_type=&source=&flagged_only=&matched_only=&tankers_only=&flag=&q=` / `GET /api/psc/vessel/{imo}` / `GET /summary` / `POST /refresh` | Port State Control detentions and bans (Paris MoU THETIS, Tokyo MoU APCIS) joined to tracked vessels; flagged hulls raise the vessel risk score |

## Admin (`/api/admin`)

### `GET /api/admin/config`

Effective configuration: `backend/settings.yaml` merged with
`settings.local.yaml`. Sections: `market`, `maritime`, `retention`,
`classification`.

### `POST /api/admin/config`

Deep-merges a partial document into the overrides and returns the effective
configuration. Unknown top-level sections -> **422**. Every change is written
to `audit_logs` as `config_updated`.

```bash
curl -X POST http://localhost:8000/api/admin/config \
  -H "Content-Type: application/json" \
  -d '{"market": {"price_anomaly_sigma": 2.5}}'
```

## Errors

FastAPI conventions: `{"detail": "..."}` with 404 / 422 / 5xx. Validation
errors return the standard FastAPI list of field errors.
