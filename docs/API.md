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

### `GET /api/market/prices?assets=BTC,ETH&exchanges=binance,kraken`

Latest stored price per (asset, exchange). Empty until the market bot
(Phase 2) writes candles.

```json
{ "timestamp": "2026-09-14T21:58:01Z", "data": [
  { "asset": "BTC", "exchange": "binance", "price": 42150.5, "24h_change_percent": null,
    "timestamp": "2026-09-14T21:57:00Z", "volume_24h_usd": null, "signal_quality": null }
] }
```

Phase 2 adds: `GET /alerts`, `GET /coordination`, `GET /history/{asset}`,
`GET /volatility/{asset}`, `POST /config`.

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
