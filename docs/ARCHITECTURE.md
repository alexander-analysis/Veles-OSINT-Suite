# VELES Architecture

VELES is a two-module OSINT platform - **market intelligence** (multi-exchange
surveillance) and **maritime intelligence** (AIS tracking + sanctions
screening) - behind one FastAPI backend and one React frontend, designed to run
perpetually on a Raspberry Pi 5.

## Data flow

```
External sources                      Backend (Python 3.11+, FastAPI)             Frontend
----------------                      -------------------------------             --------
Binance / Kraken / Coinbase  --ccxt-->  Market bot  --> market_candles
Yahoo Finance (commodities)             (Phase 2)       market_alerts        <-- /api/market/*  --> Market page
                                                        coordination_events

MarineTraffic / AIS-Hub / RTL-SDR ---> Maritime bot --> vessels, vessel_positions
OFAC SDN / EU / UN lists               (Phase 3)       sanctions_entities   <-- /api/maritime/* --> Map, breach board
                                                        sanctions_breaches
                                                        audit_logs (append-only)

                                       APScheduler (in-process, UTC)
                                       SQLite (WAL) via SQLAlchemy 2 + Alembic
                                                                             <-- /api/health, /api/admin/* --> Dashboard, Settings

Nginx (static frontend + /api proxy + WebSocket)  <--  Cloudflare Tunnel  <--  analysts' browsers
```

## Request path

* **Development**: Vite dev server on `:5173` proxies `/api` to uvicorn on `:8000`.
* **Production**: Nginx serves `frontend/dist` and proxies `/api/*` (and the
  WebSocket at `/api/maritime/stream`) to uvicorn on `127.0.0.1:8000`.
* **Fallback**: uvicorn also serves `frontend/dist` itself (history-API
  fallback), so `http://<pi>:8000` works with no Nginx at all.

## Backend layout (`backend/app`)

| Package | Responsibility |
|---------|----------------|
| `config.py` | `Settings` from env / `.env` (secrets, ports). `BACKEND_DIR` anchors every relative path. |
| `database.py` | Engine (SQLite WAL, `check_same_thread=False`), `SessionLocal`, `Base`, `init_db()` (Alembic upgrade at startup). |
| `models/` | SQLAlchemy models: `market.py`, `maritime.py`, `sanctions.py`, `audit.py`. |
| `schemas/` | Pydantic response models; datetimes render as ISO-8601 with `Z`. |
| `api/` | Routers: `health`, `market`, `maritime`, `sanctions`, `admin`, `stream` (WebSocket). Mounted in `main.py`. |
| `data/` | Bundled reference data: ports, zones/lanes, MID table, country names. |
| `bots/` | `runtime.py` (dedicated asyncio loop), `scheduler.py` (APScheduler), `market.py`, `sanctions.py`, `maritime.py`. |
| `analysis/` | Pure analysis: `market_anomaly`, `coordination`, `liquidation`, `sanctions` (index + rules), `evasion`, `transshipment`, `ports`, `geospatial`, `correlation`, `risk`. |
| `integrations/` | ccxt exchanges, Binance liquidation stream, yfinance; AIS: Digitraffic, aisstream, MarineTraffic, AISHub, NMEA/UDP; OFAC/EU/UN importers; OpenWeatherMap. |
| `utils/` | `logger` (loguru, rotating files), `time` (naive-UTC helpers), `config_store` (settings.yaml + overrides), `serialization`. |
| `reports/` | reportlab PDF builder and report content (maritime / sanctions / market). |
| `auth.py`, `notifications.py` | Optional API token middleware; webhook / e-mail alerts and daily digest. |

## Conventions

* **Timestamps** are naive UTC everywhere in the database; the API serialises
  them with a trailing `Z`. Use `app.utils.time.utcnow()` - never `datetime.now()`.
* **Configuration** is split: secrets in `.env` (never served), tunables in
  `settings.yaml` with operator overrides in `settings.local.yaml`
  (`/api/admin/config`).
* **Schema changes** go through Alembic (`alembic revision --autogenerate`).
  The app upgrades to `head` on startup; nothing calls `create_all`.
* **Audit log** (`audit_logs`) is append-only: ORM listeners *and* SQLite
  triggers reject `UPDATE`/`DELETE`. Retention purges never touch it.
* **Scheduler** jobs use `max_instances=1` and `coalesce=True` so a slow fetch
  on the Pi never stacks up.
* **Index names** are prefixed with the table name (SQLite index names are
  global per database).

## Phase roadmap

| Phase | Scope | Status |
|-------|-------|--------|
| 1 | Foundation: schema, API skeleton, frontend shell, deployment config | done |
| 2 | Market bot: exchange ingestion, 3-sigma anomalies, volume spikes, coordination, liquidation cascades, market dashboard | done |
| 2.5 | Sanctions bot: OFAC/EU/UN import + diffing, screening index, entity search/check, updates timeline | done |
| 3 | Maritime bot: AIS ingestion, OFAC/EU/UN screening, evasion/transshipment/ports/zones, map, breach board, audit log UI, WebSocket | done |
| 4 | Polish: PDF reports, settings editor, dashboard KPIs, linkage explorer, notifications, API token, position-anomaly detection, CI, docs | done (v1.0.0) |
| 5 (ecosystem tier 1) | Geopolitical event monitor (GDELT + official feeds, classification, cross-domain correlation) | done |
| 5 (ecosystem tier 1) | Blockchain tracker (OFAC wallets on BTC / ETH / TRON, cash-out and mixer detection, whale feed, co-spend clusters) | done |
| 5 (ecosystem tier 1) | Corporate intelligence (GLEIF ownership walk, sanctions exposure, shell indicators, live LEI search) | done |
| 5 (ecosystem tier 1) | Energy flow monitor (facility watch, shipment reconstruction, dark-oil indicators, price context) | done |
| 5 (ecosystem tier 1) | Cross-bot correlation engine: typed signal registry, strong-key clustering, composite alerts, unified queue | done |
| 6 (ecosystem tier 2 / 3) | Aviation, port authority, leaks, disinformation, domain / IP, legal, satellite bots | next |
