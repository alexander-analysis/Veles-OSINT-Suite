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
| `api/` | Routers: `health`, `market`, `maritime`, `admin`. Mounted in `main.py`. |
| `bots/` | `scheduler.py` (APScheduler) + bot cores (`market.py` Phase 2, `maritime.py` Phase 3). |
| `analysis/` | Pure analysis functions (anomaly, coordination, sanctions matching, evasion, transshipment). |
| `integrations/` | External clients (exchanges via ccxt, AIS providers, sanctions list importers). |
| `utils/` | `logger` (loguru, rotating files), `time` (naive-UTC helpers), `config_store` (settings.yaml + overrides). |

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
| 2 | Market bot: exchange ingestion, 3-sigma anomalies, volume spikes, coordination, market dashboard | next |
| 3 | Maritime bot: AIS ingestion, OFAC/EU/UN screening, evasion/transshipment, map, breach board, audit log UI, WebSocket | planned |
| 4 | Polish: exports (PDF/JSON/CSV), settings editor, CI, hardening | planned |
