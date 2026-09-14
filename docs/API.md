# VELES API Reference

Base URL: `http://<host>:8000` (or through Nginx on port 80). Interactive
docs: `/docs` (Swagger UI) and `/redoc`. All timestamps are UTC ISO-8601 with
a `Z` suffix. No authentication in the MVP - restrict access at the network /
Cloudflare Access layer.

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
| `GET /vessel-correlation/{mmsi}?days=30` | Linked vessels (shared owner/operator/beneficial owner, shared designated entity, STS partners, shared high-risk ports) with link strength |
| `GET /fleets?min_size=2` | Vessel groups sharing a declared owner/operator |
| `GET /breaches?authority=&severity=&status=&breach_type=&min_confidence=` | Sanctions matches; `status` defaults to open (`flagged,investigating,escalated`), use `review` for the low-confidence queue or `all` |
| `GET /breaches/{authority}` | All matches for OFAC / EU / UN |
| `PATCH /breach/{id}` `{"investigation_status": "investigating|cleared|escalated", "analyst_notes": "..."}` | Audited status change; clearing recomputes the vessel status and risk |
| `GET /evasion-patterns?event_type=&severity=&hours=` / `PATCH /evasion-patterns/{id}` | AIS gaps, renames, re-flagging, IMO conflicts, dark vessels |
| `GET /transshipment?hours=&min_confidence=` / `PATCH /transshipment/{id}` | Ship-to-ship rendezvous candidates |
| `GET /port-calls?hours=&port=&risk=&only_flagged=&open_only=` and `GET /port-calls/{24h|7d|30d}` | Port calls with dwell times and flags (`sanctioned_facility`, `unusual_dwell_time`, ...) plus per-port totals |
| `GET /ports` | Curated port reference as GeoJSON |
| `GET /sanctions-zones` | Monitoring zones as GeoJSON, grouped `ofac` / `eu` / `un` / `other` / `all` |
| `GET /shipping-lanes` / `GET /shipping-lanes/violations?hours=&context=` | Lanes/chokepoints GeoJSON; zone entries and chokepoint transits by high-risk vessels |
| `GET /audit-log?start_date=&end_date=&action_type=&vessel_id=&user=&limit=&offset=` | Immutable compliance log; `GET /audit-log/actions` lists action types |
| `POST /audit-log/export` `{"format": "json|csv", "action_type": ..., "classification": "CONFIDENTIAL"}` | Export (audited); `pdf` arrives in Phase 4 |
| `GET /status` | Bot status: sources, source errors (missing keys), last poll, counts, stream clients |
| `WS /stream` | Frames: `hello`, `vessel_positions` (batched after every poll), `breach_detected`, `transshipment_detected` |

## Sanctions (`/api/sanctions`)

| Endpoint | Purpose |
|----------|---------|
| `GET /entities?query=&type=&authority=&program=&active=&limit=&offset=` | Search listings by name / alias / IMO / MMSI with cross-authority `designating_authorities` |
| `GET /entities/{id}` | One listing |
| `POST /check-entity` `{"entity_name": "...", "entity_type": "company", "min_similarity": 0.85}` | Screen a name (audited as `sanctions_check`) |
| `GET /vessel/{mmsi}` | Recorded breaches + live screen + recommendation |
| `GET /updates?timeframe=7&authority=&type=` | Change log since the last refreshes with per-authority summary |
| `GET /programs?authority=` | Programme counts |
| `GET /report/{7days|30days|24h}` | JSON activity report |
| `GET /status` / `POST /refresh?authority=OFAC,EU` | Bot status; trigger a refresh (202) |

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
