# VELES - OSINT Intelligence Platform

Modular OSINT platform combining **market intelligence** (multi-exchange crypto
and commodity surveillance with anomaly and coordination detection) and
**maritime intelligence** (AIS vessel tracking cross-referenced against the
OFAC, EU and UN sanctions lists, with evasion detection and an immutable audit
trail). Runs 24/7 on a Raspberry Pi 5 and is reachable remotely through a
Cloudflare Tunnel.

**Status: Phase 3 (maritime intelligence) complete** - live AIS tracking
(Digitraffic keyless; aisstream.io / MarineTraffic / AISHub / RTL-SDR with
credentials), OFAC / EU / UN sanctions screening with an audited breach board,
AIS-gap / rename / re-flag / identity-conflict detection, ship-to-ship
rendezvous, port intelligence, zone & chokepoint monitoring, entity linkage,
WebSocket live map and an immutable audit log with JSON/CSV export. Phase 4
(polish & production) is next. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Quick start

```bash
# Backend (Python 3.11+)
cd backend
python -m venv venv && venv/Scripts/activate      # source venv/bin/activate on Linux/macOS
pip install -r requirements.txt
python run.py                                     # http://localhost:8000  ->  /docs, /api/health

# Frontend (Node 18+), in a second terminal
cd frontend
npm install
npm run dev                                       # http://localhost:5173
```

Or build once (`npm run build`) and let the backend serve the UI at
`http://localhost:8000`.

## Repository layout

```
backend/      FastAPI app - app/{api,models,schemas,bots,analysis,integrations,utils}, Alembic migrations, tests
frontend/     React 18 + Vite + Tailwind (light, agency-style theme)
deployment/   nginx.conf, systemd unit, pi-setup.sh, Cloudflare Tunnel guide
docs/         ARCHITECTURE.md, API.md, DEPLOYMENT.md, DATA_SOURCES.md
```

## Stack

Python 3.11+ / FastAPI / SQLAlchemy 2 / Alembic / APScheduler / SQLite (WAL)
- React 18 / Vite 5 / Tailwind 3 / Leaflet / Chart.js - Nginx - Cloudflare
Tunnel.

## Deploying to a Pi

```bash
git clone https://github.com/alexander-analysis/Veles-OSINT-Suite.git ~/veles-osint
cd ~/veles-osint && bash deployment/pi-setup.sh
```

Details in [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

## License

MIT - see [LICENSE](LICENSE).
