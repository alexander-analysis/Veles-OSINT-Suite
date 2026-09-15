# Licences and Attribution

VELES itself is MIT (see `LICENSE`). It builds on:

## Backend (Python)

| Package | Licence |
|---------|---------|
| FastAPI, Starlette, uvicorn, httpx, pydantic, pydantic-settings, python-dotenv | MIT / BSD |
| SQLAlchemy, Alembic | MIT |
| APScheduler | MIT |
| pandas, numpy, scipy | BSD |
| ccxt | MIT |
| yfinance | Apache 2.0 |
| shapely, pyproj, geopy | BSD / MIT |
| pyais | MIT |
| websockets | BSD |
| loguru | MIT |
| reportlab (open-source edition) | BSD |
| PyYAML | MIT |

## Frontend (JavaScript)

| Package | Licence |
|---------|---------|
| React, React Router, react-leaflet, react-chartjs-2, TanStack Table, lucide-react, clsx, date-fns | MIT |
| Leaflet | BSD-2-Clause |
| Chart.js | MIT |
| Turf.js | MIT |
| Vite, Tailwind CSS, PostCSS, Autoprefixer, ESLint | MIT |

## Data

| Source | Terms |
|--------|-------|
| OpenStreetMap tiles | ODbL; attribution shown in the map and footer. Respect the tile usage policy (no bulk downloads). |
| Fintraffic Digitraffic AIS | CC BY 4.0 - "Source: Fintraffic / Digitraffic" |
| OFAC SDN list | US Government work, public domain |
| EU consolidated financial sanctions list | European Commission, reuse permitted with source acknowledgement |
| UN Security Council consolidated list | United Nations, public |
| Binance / Kraken / Coinbase public market data | Subject to each exchange's API terms |
| Yahoo Finance via yfinance | Personal/research use per Yahoo's terms |
| aisstream.io, MarineTraffic, AISHub | Subject to each provider's terms when enabled |

The bundled port / zone / MID reference data was compiled from public
sources for this project and may be edited freely.
