# Data Sources

Everything VELES ingests, what it costs, and which credential switches it on.
Credentials go in `backend/.env` (never committed). Source toggles live in
`backend/settings.yaml` under `maritime.ais_sources`.

## AIS vessel positions

| Source | Coverage | Credential | Notes |
|--------|----------|------------|-------|
| **Digitraffic** (Fintraffic) | Finnish waters: Gulf of Finland, Gulf of Bothnia, northern Baltic | none | On by default. REST, ~1,100 live vessels, static data (name/IMO/type/destination). Includes traffic to the Russian terminals at Primorsk / Ust-Luga / Vysotsk / St Petersburg. |
| **aisstream.io** | Global (terrestrial + some satellite) | `AISSTREAM_API_KEY` - free key at https://aisstream.io | WebSocket; enabled in settings, activates when the key is present. Optional bounding boxes in `settings.yaml` (`bounding_boxes: [[[lat_min, lon_min], [lat_max, lon_max]]]`). |
| **MarineTraffic** | Global, best quality | `MARINETRAFFIC_API_KEY` - paid (PS07 "vessel positions in area") | Set `enabled: true` and optionally a `bbox`. |
| **AISHub** | Aggregated member feeds | `AISHUB_USERNAME` - free, but you must contribute a feed | Set `enabled: true`. |
| **NMEA over TCP** (Kystverket Norway `153.44.253.27:5631`, or any NMEA stream) | Norwegian coast (~3,000 vessels) | none | `nmea_tcp` entry in `settings.yaml`; some networks block the port - test with `nc 153.44.253.27 5631`. |
| **RTL-SDR / NMEA over UDP** | ~20-50 nm around the receiver | none (hardware) | `rtl_ais -n -h 127.0.0.1 -P 10110` or AIS-catcher `-u 127.0.0.1 10110`; set `enabled: true`. Highest-confidence source (`rtl_sdr`). Any NMEA-over-UDP feed works. |

Source reliability is recorded on every position (`ais_source`) and
reflected in `signal_quality`.

## Sanctions lists

| Authority | File | Refresh | Notes |
|-----------|------|---------|-------|
| **OFAC SDN** | `sdn.csv` + `alt.csv` (treasury.gov, redirects to the new Sanctions List Service) | every 6 h | ~19,000 listings incl. ~1,500 vessels with IMO numbers in the remarks; programmes split on `] [`. |
| **EU consolidated financial sanctions** | FSF XML (public token) | every 6 h | ~6,200 listings. Vessels subject to the EU *port-access* bans (Reg. 833/2014 Annex XLII, "shadow fleet") are **not** in this file - they are published in the Official Journal only. |
| **UN Security Council consolidated list** | XML | every 6 h | ~1,000 listings per committee (DPRK, Iran, Libya, ...). |

Each refresh is diffed against the database: new designations, relistings,
delistings, name/programme/identifier changes are written to
`sanctions_updates` and summarised in the audit log. A download that returns
fewer than half the known listings never delists anything.

## Market data

| Source | Data | Credential |
|--------|------|------------|
| Binance, Kraken, Coinbase (via ccxt) | 1-minute OHLCV for the configured assets (USDT / USD pairs) | none for public data; keys raise rate limits |
| Binance futures `!forceOrder@arr` | Liquidation orders (WebSocket) | none |
| Yahoo Finance (yfinance) | 5-minute commodity futures candles (gold, WTI, copper by default) | none |

## Reference data (bundled, editable)

* `backend/app/data/ports.py` - ~55 ports with detection radius and risk level
  (Russian export terminals, Iranian, DPRK, Syrian, Cuban, Venezuelan and
  occupied-Ukraine ports marked as sanctioned facilities).
* `backend/app/data/zones.py` - monitoring zones (sanctions / war / piracy)
  tagged with the applicable authorities, and shipping lanes / chokepoints.
* `backend/app/data/mid.py` - ITU Maritime Identification Digits -> flag state.
* `backend/app/data/countries.py` - country names used by OFAC/UN -> ISO codes.

Polygons are coarse by design; refine them for your area of interest.

## Optional context

| Source | Use | Credential |
|--------|-----|------------|
| OpenWeatherMap | Conditions at a vessel's position | `OPENWEATHERMAP_API_KEY` (free tier) |
| OpenStreetMap tiles | Base map (frontend, direct from the browser) | none - attribution shown in the UI |

## Licensing

OFAC, EU and UN lists are public data. Digitraffic is CC BY 4.0 (Fintraffic /
Digitraffic). OpenStreetMap is ODbL. Check the terms of any paid source you
enable before redistributing derived data.
