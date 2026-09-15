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

## Geopolitical events

| Source | What VELES reads | Cadence | Credential |
|--------|------------------|---------|------------|
| GDELT 2.0 event export (`data.gdeltproject.org/gdeltv2/lastupdate.txt`) | Every 15-minute CAMEO-coded event file; kept: sanctions (163/172), conflict roots 15/18/19/20 and political roots 10-14/16/17 with >= `gdelt_min_mentions` mentions and a geocoded country. Events outside the watchlist countries need twice the mentions. Headlines are reconstructed from the article URL slug and used to corroborate (or demote) GDELT's coding | 15 min | none |
| GDELT DOC 2.0 API | Topic searches (tanker/vessel seizures, port and strait closures, sanctions, energy infrastructure, trade measures) | 30 min, >= 15 s between calls | none - the API throttles aggressively; rate-limited runs simply stop and retry next time |
| UK FCDO news (Atom) | Official statements and sanctions announcements | 30 min | none |
| UN press releases (RSS) | Security Council / General Assembly output | 30 min | none |
| OFAC recent actions (HTML) | Designation / delisting actions (OFAC no longer publishes RSS) | 30 min | none |
| RT, TASS, Global Times (RSS) | State-media headlines - stored only when they hit a monitored topic, tagged `state_media`, reliability 0.3-0.35 | 30 min | none |

Feeds are configurable under `geopolitical.official_feeds` / `doc_topics` in `settings.yaml`.

## Blockchain

| Source | What VELES reads | Cadence | Credential |
|--------|------------------|---------|------------|
| OFAC SDN remarks (`Digital Currency Address - XBT/ETH/USDT/TRX/...`) | ~500 sanctioned addresses across Bitcoin, Ethereum, Tron, Monero, Litecoin and others become watched wallets (owner, programmes) | hourly sync | none |
| Blockstream Esplora (`blockstream.info/api`) | Bitcoin address stats and newest 25 transactions per watched address | 12 addresses per 10 min (rotation) | none |
| PublicNode Ethereum RPC (`ethereum-rpc.publicnode.com`) | Batched balances / nonces of all watched addresses; newest block in full for native whales; `eth_getLogs` for USDT / USDC / DAI transfers to or from sanctioned and mixer addresses (complete coverage) and stablecoin whales (sampled) | 3 min | none (`ETHEREUM_RPC_URL` overrides the endpoint) |
| Tronscan (`apilist.tronscanapi.com`) | Account balances incl. USDT-TRC20 and newest TRC-20 transfers | 6 addresses per 10 min | none |
| blockchain.com websocket (`unconfirmed_sub`) | Every unconfirmed Bitcoin transaction, matched locally against sanctioned / mixer addresses and the whale threshold | continuous (~5 tx/s, negligible CPU) | none |
| mempool.space prices, CoinGecko simple price | BTC / TRX USD prices when the market bot has no candle | 10 min | none |
| Curated labels (`backend/app/data/crypto_labels.py`) | Exchange hot wallets and mixer contracts used for cash-out / mixer detection; extend with `POST /api/blockchain/wallets` | - | - |

Blockchair is deliberately not used: its keyless tier blacklists an IP after a handful of calls.

## Corporate registries

| Source | What VELES reads | Cadence | Credential |
|--------|------------------|---------|------------|
| Sanctions lists (OFAC / EU / UN company listings, vessel owners) | ~11,000 seed companies; the EU list's English strong alias is now preferred over other-language variants | daily | none |
| GLEIF API (`api.gleif.org/api/v1`) | LEI records (legal name, other-language names, addresses, status, legal form, creation date), direct / ultimate parents or the reporting exception (`NO_KNOWN_PERSON`, `NON_CONSOLIDATING`, ...), direct children | 40 companies per 10 min (~1 request/s); full pass over the seeds in ~2 days, re-checked every 30 days | none |
| SEC EDGAR company browse (Atom) | CIK, SIC description and business address for US-registered entities | during enrichment | none - the SEC asks for a contact e-mail in the User-Agent (`EDGAR_CONTACT_EMAIL`) |
| Companies House / OpenCorporates | Not wired yet - both need API keys (`COMPANIES_HOUSE_API_KEY`, `OPENCORPORATES_API_TOKEN` are reserved in `.env.example`) | - | key |

Name matching strips legal-form tokens (LLC, PAO, GmbH, "Public Joint Stock Company", ...) and compares the listed name and its published aliases against the GLEIF legal name and other names; an LEI is attached only above `corporate.min_name_similarity` (0.9). EDGAR full-text search is not used - it returns 403 to non-browser clients.

## Energy flows

| Source | What VELES reads | Cadence | Credential |
|--------|------------------|---------|------------|
| Curated facilities (`backend/app/data/energy_facilities.py`) | ~60 export terminals, discharge hubs, refineries, LNG plants and STS anchorages with capacities and sanctions flags | synced every 12 h | - |
| AIS static data (Digitraffic, aisstream) | Draught and hull dimensions (A+B length, C+D beam) now kept on the vessel; port calls snapshot draught at arrival / departure | with every position | as for AIS |
| Own port-call / evasion / STS data | Laden departures become shipments (size class -> DWT -> barrels); AIS gaps, spoofing, identity changes and STS meetings after a sanctioned loading become dark-oil indicators | 5 - 15 min | - |
| Market bot commodities | Brent (`BZ=F`), WTI (`CL=F`), Henry Hub (`NG=F`) and Dutch TTF (`TTF=F`) from yfinance feed the price-context correlation | 5 min | none |
| EIA / NASA FIRMS | Reserved (`EIA_API_KEY`, `NASA_FIRMS_MAP_KEY`) for official flow statistics and refinery-fire detection - not wired yet | - | key |

Cargo volumes are coarse estimates (size class x 95 % x barrels/tonne, scaled by draught) meant for trend and utilisation, not for cargo accounting.

## Optional context

| Source | Use | Credential |
|--------|-----|------------|
| OpenWeatherMap | Conditions at a vessel's position | `OPENWEATHERMAP_API_KEY` (free tier) |
| OpenStreetMap tiles | Base map (frontend, direct from the browser) | none - attribution shown in the UI |

## Licensing

OFAC, EU and UN lists are public data. Digitraffic is CC BY 4.0 (Fintraffic /
Digitraffic). OpenStreetMap is ODbL. Check the terms of any paid source you
enable before redistributing derived data.
