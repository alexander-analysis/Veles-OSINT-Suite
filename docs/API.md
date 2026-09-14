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

### `GET /api/maritime/vessels?bbox=-180,-90,180,90&risk_filter=all&limit=5000`

Current vessel positions as a GeoJSON `FeatureCollection`. `risk_filter` is
`all` | `flagged` | `breach`. `bbox` is `min_lon,min_lat,max_lon,max_lat`
(422 if malformed).

```json
{ "type": "FeatureCollection", "timestamp": "2026-09-14T21:58:01Z",
  "vessel_count": 1, "breach_count": 0,
  "features": [ { "type": "Feature",
    "geometry": { "type": "Point", "coordinates": [2.3522, 48.8566] },
    "properties": { "mmsi": "123456789", "imo": "9876543", "name": "Example", "flag": "PA",
      "owner": null, "ship_type": "Tanker", "speed": 12.5, "heading": 45.0,
      "sanctioned_status": "clear", "risk_score": null, "last_update": "2026-09-14T21:50:00Z",
      "ais_source": "ais_hub", "marker_color": "#2ecc71" } } ] }
```

Marker colours: clear `#2ecc71`, flagged `#f39c12`, breach `#e74c3c`.

Phase 3 adds: `GET /vessel/{mmsi}`, `GET /breaches`, `GET /evasion-patterns`,
`GET /transshipment`, `GET /audit-log`, `POST /audit-log/export`,
`WS /stream`.

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
