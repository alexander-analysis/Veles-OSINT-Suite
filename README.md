# VELES - OSINT Intelligence Platform

Modular OSINT platform combining **market intelligence** (multi-exchange crypto
and commodity surveillance with anomaly and coordination detection) and
**maritime intelligence** (AIS vessel tracking cross-referenced against the
OFAC, EU and UN sanctions lists, with evasion detection and an immutable audit
trail). Runs 24/7 on a Raspberry Pi 5 and is reachable remotely through a
Cloudflare Tunnel.

**Status: v1.1 - core platform complete; ecosystem tiers 1-3 live: geopolitical, blockchain, corporate, energy, fusion engine, aviation, leaks, narratives, infrastructure and legal monitors.**

| Module | What it does |
|--------|--------------|
| Market intelligence | 1-minute candles from Binance, Kraken and Coinbase plus commodity futures; 3-sigma price anomalies, volume spikes, cross-exchange coordination, Binance liquidation cascades; charts, alert board, PDF/CSV briefs |
| Sanctions monitoring | OFAC SDN, EU consolidated and UN Security Council lists refreshed every 6 h and diffed (new designations, delistings, changes); entity search and audited screening checks; programme tracking |
| Maritime intelligence | Live AIS (Digitraffic keyless; aisstream.io / MarineTraffic / AISHub / NMEA feeds / RTL-SDR with credentials or hardware); IMO/name/owner screening against all three lists; AIS gaps, renames, re-flagging, identity conflicts, spoofed positions; ship-to-ship rendezvous; port intelligence; monitored zones and chokepoints; entity linkage and risk scoring; live map over WebSocket |
| Geopolitical monitor | GDELT 2.0 events and articles, UK FCDO, UN and OFAC announcements classified into conflict / sanctions / maritime incident / port closure / infrastructure / trade / political with severity and impact notes; every event is correlated against market alerts, sanctions breaches, evasion events, STS rendezvous and list changes inside a 24 h window |
| Blockchain tracker | Every OFAC digital-currency address (Bitcoin, Ethereum, Tron and more) watched through keyless public APIs: balances and token holdings, new transfers scored for exchange cash-outs, mixer use and sanctioned counterparties, a live Bitcoin mempool whale / sanctioned-address feed, Ethereum stablecoin flow capture and common-input clustering |
| Corporate intelligence | Every listed company and vessel owner resolved through GLEIF in rotation: LEI records, direct / ultimate parents, subsidiaries; unlisted companies under or above a listed party surface as sanctions exposure; shell and opacity indicators (secrecy jurisdictions, undisclosed parents, lapsed registrations, fresh formations); live LEI search with import-and-walk |
| Energy flow monitor | ~60 curated terminals, refineries, LNG plants and STS anchorages watched through AIS: tanker calls with draught changes become shipments (origin, destination, estimated barrels), dark-oil indicators (loading at sanctioned facilities, AIS gaps and spoofing after loading, STS transfers, anchorage loitering, identity changes) and daily flow snapshots correlated with Brent / WTI |
| Intelligence fusion | Every bot output becomes a typed signal (vessels, listed parties, wallets, companies, facilities, countries, assets); cross-domain pairs are scored and clusters spanning three or more domains become composite alerts with a narrative - plus a unified severity-ranked queue and a per-domain timeline |
| Monitors (tier 2 / 3) | Sanctioned aircraft on ADS-B (adsb.lol / OpenSky), ransomware and breach postings matched to tracked companies and sectors, state-media narrative clustering against official coverage, web infrastructure of listed parties (RDAP, DNS, hosting, certificate transparency), OFAC penalties / DOJ prosecutions / court dockets naming listed parties |
| Compliance | Append-only audit log (enforced in the ORM and the database), classification markings, PDF/JSON/CSV intelligence reports, optional API token, webhook / e-mail alerts and a daily digest |

Docs: [ARCHITECTURE](docs/ARCHITECTURE.md) - [API](docs/API.md) - [DEPLOYMENT](docs/DEPLOYMENT.md) - [DATA_SOURCES](docs/DATA_SOURCES.md) - [USER_GUIDE](docs/USER_GUIDE.md) - [DEVELOPMENT](docs/DEVELOPMENT.md) - [SECURITY](docs/SECURITY.md) - [LICENSES](docs/LICENSES.md)

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
docs/         architecture, API, deployment, data sources, user/developer guides, security, licences
.github/      CI (pytest + flake8 on 3.11/3.13, eslint + build on Node 22)
```

## Stack

Python 3.11+ / FastAPI / SQLAlchemy 2 / Alembic / APScheduler / SQLite (WAL) /
reportlab - React 18 / Vite 5 / Tailwind 3 / Leaflet / Chart.js - Nginx -
Cloudflare Tunnel.

## Deploying to a Pi

```bash
git clone https://github.com/alexander-analysis/Veles-OSINT-Suite.git ~/veles-osint
cd ~/veles-osint && bash deployment/pi-setup.sh
```

Then add keys to `backend/.env` (see [docs/DATA_SOURCES.md](docs/DATA_SOURCES.md) -
`AISSTREAM_API_KEY` gives the map global coverage) and follow
[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) for the tunnel and hardening.

## License

MIT - see [LICENSE](LICENSE).
