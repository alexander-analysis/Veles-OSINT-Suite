"""GDELT (Global Database of Events, Language and Tone) - keyless.

* Events 2.0: a new CSV export every 15 minutes (``lastupdate.txt`` points at
  it).  Structured CAMEO-coded events with actors, geolocation, Goldstein
  scale and mention counts.
* DOC 2.0 API: full-text article search (rate limit: one request every 5 s).
"""

import asyncio
import io
import time
import zipfile
from dataclasses import dataclass, field
from datetime import datetime

import httpx
import pandas as pd

from app.utils.logger import logger

log = logger.bind(component="geopolitical")

LASTUPDATE_URL = "https://data.gdeltproject.org/gdeltv2/lastupdate.txt"
DOC_API_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
UA = {"User-Agent": "VELES-OSINT/1.0 (research)"}

EVENT_COLUMNS = [
    "GlobalEventID", "Day", "MonthYear", "Year", "FractionDate",
    "Actor1Code", "Actor1Name", "Actor1CountryCode", "Actor1KnownGroupCode", "Actor1EthnicCode", "Actor1Religion1Code", "Actor1Religion2Code", "Actor1Type1Code", "Actor1Type2Code", "Actor1Type3Code",
    "Actor2Code", "Actor2Name", "Actor2CountryCode", "Actor2KnownGroupCode", "Actor2EthnicCode", "Actor2Religion1Code", "Actor2Religion2Code", "Actor2Type1Code", "Actor2Type2Code", "Actor2Type3Code",
    "IsRootEvent", "EventCode", "EventBaseCode", "EventRootCode", "QuadClass", "GoldsteinScale", "NumMentions", "NumSources", "NumArticles", "AvgTone",
    "Actor1Geo_Type", "Actor1Geo_FullName", "Actor1Geo_CountryCode", "Actor1Geo_ADM1Code", "Actor1Geo_ADM2Code", "Actor1Geo_Lat", "Actor1Geo_Long", "Actor1Geo_FeatureID",
    "Actor2Geo_Type", "Actor2Geo_FullName", "Actor2Geo_CountryCode", "Actor2Geo_ADM1Code", "Actor2Geo_ADM2Code", "Actor2Geo_Lat", "Actor2Geo_Long", "Actor2Geo_FeatureID",
    "ActionGeo_Type", "ActionGeo_FullName", "ActionGeo_CountryCode", "ActionGeo_ADM1Code", "ActionGeo_ADM2Code", "ActionGeo_Lat", "ActionGeo_Long", "ActionGeo_FeatureID",
    "DATEADDED", "SOURCEURL",
]

CAMEO_ROOT = {
    "01": "public statement", "02": "appeal", "03": "intent to cooperate", "04": "consultation", "05": "diplomatic cooperation",
    "06": "material cooperation", "07": "aid", "08": "concession", "09": "investigation", "10": "demand", "11": "disapproval",
    "12": "rejection", "13": "threat", "14": "protest", "15": "force posture", "16": "reduced relations", "17": "coercion",
    "18": "assault", "19": "armed clash", "20": "mass violence",
}
CAMEO_BASE = {
    "163": "sanctions / embargo imposed", "172": "administrative sanctions imposed", "171": "property seized", "173": "arrest or detention",
    "174": "expulsion", "175": "martial law", "181": "abduction", "182": "physical assault", "183": "suicide / car bombing",
    "184": "torture", "185": "assassination", "186": "attack on civilians", "190": "fighting", "191": "blockade", "192": "occupation",
    "193": "small arms fight", "194": "artillery / aerial fight", "195": "unconventional weapons", "196": "missile strike",
    "201": "mass expulsion", "202": "mass killings", "203": "ethnic cleansing", "204": "weapons of mass destruction",
    "141": "demonstration", "145": "riot", "150": "military posture", "151": "police alert", "152": "military alert",
    "153": "mobilisation", "154": "military exercise", "161": "diplomatic relations reduced", "162": "aid cut", "164": "halted negotiations",
    "130": "threat", "138": "threat of force", "139": "ultimatum",
}

# GDELT geo codes are FIPS 10-4; actor codes are ISO 3166-1 alpha-3.  Both mapped to alpha-2.
FIPS_TO_ISO2 = {
    "RS": "RU", "UP": "UA", "IR": "IR", "KN": "KP", "KS": "KR", "CH": "CN", "US": "US", "UK": "GB", "GM": "DE", "FR": "FR", "TU": "TR", "IS": "IL", "IZ": "IQ",
    "SY": "SY", "SA": "SA", "AE": "AE", "IN": "IN", "PK": "PK", "AF": "AF", "YM": "YE", "LY": "LY", "EG": "EG", "SU": "SD", "ET": "ET", "SO": "SO", "NI": "NG",
    "CU": "CU", "VE": "VE", "MX": "MX", "BR": "BR", "CO": "CO", "AR": "AR", "JA": "JP", "TW": "TW", "VM": "VN", "PP": "PG", "AS": "AU", "NZ": "NZ", "ID": "ID",
    "MY": "MY", "SN": "SG", "TH": "TH", "PH": "PH", "BG": "BD", "CE": "LK", "BM": "MM", "KZ": "KZ", "UZ": "UZ", "AJ": "AZ", "AM": "AM", "GG": "GE", "BO": "BY",
    "PL": "PL", "LH": "LT", "LG": "LV", "EN": "EE", "FI": "FI", "SW": "SE", "NO": "NO", "DA": "DK", "NL": "NL", "BE": "BE", "SP": "ES", "PO": "PT", "IT": "IT",
    "GR": "GR", "CY": "CY", "MT": "MT", "AU": "AT", "SZ": "CH", "HU": "HU", "RO": "RO", "BU": "BG", "SR": "RS", "MD": "MD", "HR": "HR", "BK": "BA", "MK": "MK",
    "LE": "LB", "JO": "JO", "KU": "KW", "QA": "QA", "BA": "BH", "MU": "OM", "MO": "MA", "AG": "DZ", "TS": "TN", "CD": "TD", "ML": "ML", "NG": "NE", "GH": "GH",
    "KE": "KE", "TZ": "TZ", "SF": "ZA", "AO": "AO", "CG": "CD", "CF": "CG", "CM": "CM", "SL": "SL", "LI": "LR", "GV": "GN", "IV": "CI", "SG": "SN", "CA": "CA",
    "HK": "HK", "MG": "MN", "PA": "PY", "PE": "PE", "CI": "CL", "EC": "EC", "PM": "PA", "HA": "HT", "DR": "DO", "NU": "NI", "HO": "HN", "GT": "GT", "ES": "SV",
    "RP": "PH", "CB": "KH", "LA": "LA", "NP": "NP", "TX": "TM", "TI": "TJ", "KG": "KG", "MJ": "ME", "EZ": "CZ", "LO": "SK", "SI": "SI", "IC": "IS", "EI": "IE",
    "GA": "GM", "ER": "ER", "DJ": "DJ", "RW": "RW", "UG": "UG", "MZ": "MZ", "ZI": "ZW", "ZA": "ZM", "WA": "NA", "BC": "BW", "MI": "MW", "MA": "MG", "MP": "MU",
}
ISO3_TO_ISO2 = {
    "RUS": "RU", "UKR": "UA", "IRN": "IR", "PRK": "KP", "KOR": "KR", "CHN": "CN", "USA": "US", "GBR": "GB", "DEU": "DE", "FRA": "FR", "TUR": "TR", "ISR": "IL",
    "IRQ": "IQ", "SYR": "SY", "SAU": "SA", "ARE": "AE", "IND": "IN", "PAK": "PK", "AFG": "AF", "YEM": "YE", "LBY": "LY", "EGY": "EG", "SDN": "SD", "ETH": "ET",
    "SOM": "SO", "NGA": "NG", "CUB": "CU", "VEN": "VE", "MEX": "MX", "BRA": "BR", "COL": "CO", "ARG": "AR", "JPN": "JP", "TWN": "TW", "VNM": "VN", "AUS": "AU",
    "IDN": "ID", "MYS": "MY", "SGP": "SG", "THA": "TH", "PHL": "PH", "BGD": "BD", "MMR": "MM", "KAZ": "KZ", "AZE": "AZ", "ARM": "AM", "GEO": "GE", "BLR": "BY",
    "POL": "PL", "LTU": "LT", "LVA": "LV", "EST": "EE", "FIN": "FI", "SWE": "SE", "NOR": "NO", "DNK": "DK", "NLD": "NL", "BEL": "BE", "ESP": "ES", "PRT": "PT",
    "ITA": "IT", "GRC": "GR", "CYP": "CY", "MLT": "MT", "AUT": "AT", "CHE": "CH", "HUN": "HU", "ROU": "RO", "BGR": "BG", "SRB": "RS", "MDA": "MD", "LBN": "LB",
    "JOR": "JO", "KWT": "KW", "QAT": "QA", "BHR": "BH", "OMN": "OM", "MAR": "MA", "DZA": "DZ", "TUN": "TN", "KEN": "KE", "ZAF": "ZA", "CAN": "CA", "HKG": "HK",
    "CZE": "CZ", "SVK": "SK", "IRL": "IE", "PAN": "PA", "LBR": "LR", "MHL": "MH", "GAB": "GA", "CMR": "CM", "SLE": "SL", "COM": "KM", "PLW": "PW",
}


@dataclass
class GdeltEvent:
    global_event_id: str
    event_date: datetime
    root_code: str
    base_code: str
    event_code: str
    quad_class: int
    goldstein: float
    mentions: int
    sources: int
    articles: int
    tone: float
    actor1: str | None
    actor1_country: str | None
    actor2: str | None
    actor2_country: str | None
    location: str | None
    country: str | None
    lat: float | None
    lon: float | None
    source_url: str
    added: datetime | None = None
    extra: dict = field(default_factory=dict)


def _iso2_from_actor(code) -> str | None:
    return ISO3_TO_ISO2.get(str(code)) if isinstance(code, str) and code else None


def _iso2_from_geo(code) -> str | None:
    return FIPS_TO_ISO2.get(str(code)) if isinstance(code, str) and code else None


def parse_events_csv(raw: bytes) -> list[GdeltEvent]:
    frame = pd.read_csv(io.BytesIO(raw), sep="\t", header=None, names=EVENT_COLUMNS, dtype=str, keep_default_na=False, quoting=3, on_bad_lines="skip")
    events: list[GdeltEvent] = []
    for row in frame.itertuples(index=False):
        try:
            code = str(row.EventCode).zfill(3) if row.EventCode else ""
            events.append(
                GdeltEvent(
                    global_event_id=str(row.GlobalEventID),
                    event_date=datetime.strptime(str(row.Day), "%Y%m%d"),
                    root_code=str(row.EventRootCode).zfill(2),
                    base_code=str(row.EventBaseCode).zfill(3),
                    event_code=code,
                    quad_class=int(row.QuadClass or 0),
                    goldstein=float(row.GoldsteinScale or 0),
                    mentions=int(row.NumMentions or 0),
                    sources=int(row.NumSources or 0),
                    articles=int(row.NumArticles or 0),
                    tone=float(row.AvgTone or 0),
                    actor1=row.Actor1Name or None,
                    actor1_country=_iso2_from_actor(row.Actor1CountryCode),
                    actor2=row.Actor2Name or None,
                    actor2_country=_iso2_from_actor(row.Actor2CountryCode),
                    location=row.ActionGeo_FullName or None,
                    country=_iso2_from_geo(row.ActionGeo_CountryCode),
                    lat=float(row.ActionGeo_Lat) if row.ActionGeo_Lat else None,
                    lon=float(row.ActionGeo_Long) if row.ActionGeo_Long else None,
                    source_url=row.SOURCEURL,
                    added=datetime.strptime(str(row.DATEADDED), "%Y%m%d%H%M%S") if row.DATEADDED else None,
                )
            )
        except (ValueError, TypeError):
            continue
    return events


class GdeltClient:
    def __init__(self) -> None:
        self.last_export_url: str | None = None
        self._last_doc_call = 0.0
        self._doc_lock = asyncio.Lock()
        self.min_interval = 15.0  # the documented limit is 5 s, in practice the API throttles harder
        self.rate_limited = False

    async def latest_export_url(self) -> str | None:
        async with httpx.AsyncClient(timeout=30, headers=UA, follow_redirects=True) as client:
            response = await client.get(LASTUPDATE_URL)
            response.raise_for_status()
        for line in response.text.splitlines():
            parts = line.split()
            if len(parts) == 3 and parts[2].endswith(".export.CSV.zip"):
                return parts[2]
        return None

    async def fetch_latest_events(self) -> list[GdeltEvent]:
        """Download the newest 15-minute export (skips if already processed)."""
        url = await self.latest_export_url()
        if not url or url == self.last_export_url:
            return []
        async with httpx.AsyncClient(timeout=120, headers=UA, follow_redirects=True) as client:
            response = await client.get(url.replace("http://", "https://"))
            response.raise_for_status()
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            name = archive.namelist()[0]
            raw = archive.read(name)
        self.last_export_url = url
        events = parse_events_csv(raw)
        log.info("gdelt events: {} rows in {}", len(events), url.rsplit("/", 1)[-1])
        return events

    async def search_articles(self, query: str, timespan: str = "2h", max_records: int = 50) -> list[dict]:
        """DOC 2.0 article list for a query - throttled to the documented one call per 5 seconds."""
        async with self._doc_lock:
            wait = self.min_interval - (time.monotonic() - self._last_doc_call)
            if wait > 0:
                await asyncio.sleep(wait)
            params = {"query": query, "mode": "artlist", "maxrecords": max_records, "format": "json", "timespan": timespan, "sort": "datedesc"}
            async with httpx.AsyncClient(timeout=60, headers=UA) as client:
                response = await client.get(DOC_API_URL, params=params)
            self._last_doc_call = time.monotonic()
        body = response.text.strip()
        if response.status_code == 429 or body.startswith("Please limit requests"):
            log.warning("gdelt doc api rate limited")
            self.rate_limited = True
            return []
        response.raise_for_status()
        self.rate_limited = False
        if not body.startswith("{"):
            return []
        return response.json().get("articles", [])
