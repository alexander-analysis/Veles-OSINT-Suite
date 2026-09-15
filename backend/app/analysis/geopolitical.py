"""Geopolitical event classification and cross-domain correlation rules.

Pure functions: turn GDELT rows / feed items into ``EventDraft`` records and
score how an event relates to market, maritime and sanctions signals.
"""

import re
from dataclasses import dataclass, field
from datetime import datetime

from app.data.countries import COUNTRY_NAME_TO_ISO
from app.integrations.gdelt import CAMEO_BASE, CAMEO_ROOT, GdeltEvent

# CAMEO root/base codes -> VELES event type
SANCTIONS_CODES = {"163", "172"}
CONFLICT_ROOTS = {"15", "18", "19", "20"}
POLITICAL_ROOTS = {"10", "11", "12", "13", "14", "16", "17"}
PRESS_RELEASE_DOMAINS = ("prnewswire", "businesswire", "globenewswire", "newswire", "press-release", "einpresswire", "accesswire")

DEMONYMS = {
    "russian": "RU", "ukrainian": "UA", "iranian": "IR", "north korean": "KP", "chinese": "CN", "american": "US", "british": "GB", "israeli": "IL",
    "syrian": "SY", "turkish": "TR", "saudi": "SA", "emirati": "AE", "indian": "IN", "venezuelan": "VE", "cuban": "CU", "libyan": "LY", "yemeni": "YE",
    "houthi": "YE", "taiwanese": "TW", "german": "DE", "french": "FR", "polish": "PL", "finnish": "FI", "estonian": "EE", "greek": "GR", "egyptian": "EG",
    "sudanese": "SD", "pakistani": "PK", "iraqi": "IQ", "lebanese": "LB", "belarusian": "BY", "georgian": "GE", "kazakh": "KZ", "malaysian": "MY", "panamanian": "PA",
}
COUNTRY_PATTERNS = sorted(({**{k: v for k, v in COUNTRY_NAME_TO_ISO.items() if len(k) > 3}, **DEMONYMS}).items(), key=lambda kv: -len(kv[0]))

SECTOR_KEYWORDS = {
    "energy": ("oil", "crude", "tanker", "lng", "gas", "pipeline", "refinery", "opec", "petroleum", "fuel", "terminal"),
    "shipping": ("tanker", "vessel", "ship", "port", "strait", "canal", "maritime", "cargo", "container", "shipping", "fleet", "seized", "detained", "boarded"),
    "finance": ("sanction", "bank", "swift", "asset", "freeze", "crypto", "stablecoin", "wallet", "tariff", "export control", "designation", "ofac"),
    "defence": ("missile", "drone", "strike", "airstrike", "troops", "military", "naval", "warship", "attack", "offensive", "ceasefire"),
    "trade": ("tariff", "embargo", "export ban", "quota", "trade", "customs", "import ban"),
}
KEYWORD_EVENT_TYPES = [
    ("sanctions", re.compile(r"sanction|\bofac\b|designat|asset freeze|blacklist|export control|price cap|\bsdn\b")),
    ("port_closure", re.compile(r"\b(ports?|strait|canal|terminals?|harbou?rs?)\b.{0,40}\b(closed|closure|closes|shut|suspend|blockad|halted|reopen)|\bblockade\b")),
    ("maritime_incident", re.compile(r"\b(tankers?|vessels?|ships?|freighters?|boats?)\b.{0,50}\b(seized|detained|boarded|attacked|hijack|struck|sank|sinking|collision|fire|drifting|aground)"
                                     r"|\b(seize|detain|board|attack|hijack|intercept)\w*\b.{0,50}\b(tankers?|vessels?|ships?|freighters?)|shadow fleet|dark fleet|\bhormuz\b|red sea|bab el.mandeb")),
    ("infrastructure", re.compile(r"pipeline|refiner(y|ies)|lng terminal|power plant|substation|oil depot|power grid|nuclear plant|export terminal")),
    ("trade", re.compile(r"tariff|embargo|export ban|import ban|quota|trade war|customs dut")),
    ("conflict", re.compile(r"airstrike|missile|drone|offensive|shelling|ceasefire|invasion|clash|explosion|attack|strikes? on|troops|warship")),
    ("political", re.compile(r"\bcoup\b|martial law|state of emergency|election|parliament|resign|protest|arrest|detained|impeach")),
]
# Countries whose events matter most for sanctions / maritime work; events elsewhere need more coverage to be kept
DEFAULT_WATCHLIST = {"RU", "UA", "BY", "IR", "IQ", "SY", "LB", "IL", "PS", "YE", "SA", "AE", "KP", "KR", "CN", "TW", "VE", "CU", "LY", "SD", "SS", "MM", "TR", "EG", "GE", "AM", "AZ", "KZ", "PK", "AF", "SO", "ER", "NG", "ML", "NE", "BF", "CD", "ET", "IN", "US", "GB", "EU", "FI", "EE", "LV", "LT", "PL", "GR", "CY", "MT", "PA", "LR", "MH", "GA", "CM", "KM", "SL", "HN"}
SLUG_STOP = {"html", "htm", "php", "asp", "aspx", "amp", "index", "article", "articles", "news", "story", "stories", "id", "www"}
HIGH_IMPACT_TERMS = ("hormuz", "bab el-mandeb", "red sea", "suez", "black sea", "baltic", "pipeline", "refinery", "lng", "tanker", "sanction", "ofac", "nuclear", "missile", "blockade")


@dataclass
class EventDraft:
    event_type: str
    title: str
    description: str
    event_date: datetime
    source: str
    source_id: str
    source_urls: list[str]
    severity: str
    confidence: float
    country_primary: str | None = None
    country_secondary: str | None = None
    region: str | None = None
    lat: float | None = None
    lon: float | None = None
    keywords: list[str] = field(default_factory=list)
    sectors: list[str] = field(default_factory=list)
    affected_countries: list[str] = field(default_factory=list)
    goldstein: float | None = None
    mentions: int | None = None
    market_impact: str | None = None
    supply_chain_impact: str | None = None


ABBREVIATIONS = [
    (re.compile(r"\b(US|U\.S\.|USA)\b"), "US"),
    (re.compile(r"\b(UK|U\.K\.)\b"), "GB"),
    (re.compile(r"\bEU\b"), "EU"),
    (re.compile(r"\bUAE\b"), "AE"),
    (re.compile(r"\bDPRK\b"), "KP"),
]


def detect_countries(text: str) -> list[str]:
    """ISO alpha-2 codes for country names / demonyms in ``text`` (plus case-sensitive abbreviations: US, UK, EU, UAE, DPRK)."""
    lowered = text.lower()
    found: list[str] = []
    for name, iso in COUNTRY_PATTERNS:
        if re.search(rf"\b{re.escape(name)}\b", lowered) and iso not in found:
            found.append(iso)
    for pattern, iso in ABBREVIATIONS:
        if pattern.search(text) and iso not in found:
            found.append(iso)
    return found


def detect_sectors(text: str) -> list[str]:
    lowered = text.lower()
    return [sector for sector, words in SECTOR_KEYWORDS.items() if any(w in lowered for w in words)]


def classify_text_or_none(text: str) -> str | None:
    lowered = text.lower()
    for event_type, pattern in KEYWORD_EVENT_TYPES:
        if pattern.search(lowered):
            return event_type
    return None


def classify_text(text: str) -> str:
    return classify_text_or_none(text) or "political"


def severity_from_text(text: str, base: str = "medium") -> str:
    lowered = text.lower()
    hits = sum(1 for term in HIGH_IMPACT_TERMS if term in lowered)
    if hits >= 3:
        return "critical"
    if hits >= 2:
        return "high"
    if hits == 1:
        return "medium" if base == "low" else base
    return base


def impact_assessment(event_type: str, sectors: list[str], countries: list[str]) -> tuple[str | None, str | None]:
    market = supply = None
    if "energy" in sectors:
        market = "Energy price sensitivity: watch crude/product spreads and gas benchmarks"
        supply = "Possible disruption to loading/discharge at affected terminals and routes"
    if event_type in ("port_closure", "maritime_incident"):
        supply = "Shipping route / port disruption - expect rerouting, delays and freight-rate moves"
    if event_type == "sanctions":
        market = market or "Sanctions action: expect repricing of exposed assets and screening hits on newly designated entities"
        supply = supply or "New designations may strand cargoes or vessels tied to listed parties"
    if event_type == "conflict" and any(c in countries for c in ("RU", "UA", "IR", "IL", "YE", "SA")):
        market = market or "Conflict in an energy-exporting region: risk premium on oil and gas"
    return market, supply


# ------------------------------------------------------------------ GDELT
def title_from_url(url: str) -> str | None:
    """Most news URLs carry a readable slug ("/2026/09/15/tanker-seized-off-oman.html") - far better than GDELT's actor codes."""
    path = re.sub(r"[?#].*$", "", url or "")
    segments = [seg for seg in path.split("/")[3:] if seg]
    best = ""
    for seg in reversed(segments):
        seg = re.sub(r"\.(html?|php|aspx?|amp)$", "", seg, flags=re.I)
        words = [w for w in re.split(r"[-_+]+", seg) if w and not w.isdigit() and w.lower() not in SLUG_STOP and len(w) > 1]
        if len(words) >= 4 and sum(len(w) for w in words) > len(words) * 3:
            best = " ".join(words)
            break
    if not best or re.search(r"\d{6,}", best):
        return None
    return best[:1].upper() + best[1:]


def _step_down(severity: str) -> str:
    order = ["low", "medium", "high", "critical"]
    return order[max(0, order.index(severity) - 1)]


def draft_from_gdelt(event: GdeltEvent, min_mentions: int = 8, watchlist: set[str] | None = None) -> EventDraft | None:
    root, base = event.root_code, event.base_code
    interesting = base in SANCTIONS_CODES or root in CONFLICT_ROOTS or root in POLITICAL_ROOTS
    if not interesting or event.mentions < min_mentions or not event.country:
        return None
    if any(d in event.source_url for d in PRESS_RELEASE_DOMAINS):
        return None
    watch = DEFAULT_WATCHLIST if watchlist is None else watchlist
    on_watchlist = any(c in watch for c in (event.country, event.actor1_country, event.actor2_country) if c)
    if not on_watchlist and base not in SANCTIONS_CODES and event.mentions < 2 * min_mentions:
        return None
    if base in SANCTIONS_CODES:
        event_type = "sanctions"
    elif root in CONFLICT_ROOTS or base in ("171", "191", "192"):
        event_type = "conflict"
    else:
        event_type = "political"
    magnitude = -event.goldstein
    if root in ("18", "19", "20") and event.mentions >= 50:
        severity = "critical"
    elif root in ("18", "19", "20") or (base in SANCTIONS_CODES and event.mentions >= 30) or magnitude >= 9:
        severity = "high"
    elif root in ("15", "17") or base in SANCTIONS_CODES or magnitude >= 5:
        severity = "medium"
    else:
        severity = "low"
    if not on_watchlist:
        severity = _step_down(severity)
    if severity in ("high", "critical") and event.sources < 2 and event.mentions < 20:
        severity = "medium"  # single-outlet local incident reported many times, not a multi-source event
    label = CAMEO_BASE.get(base) or CAMEO_ROOT.get(root, "event")
    location = re.sub(r"[\ufffd*]+", "", event.location or "").strip() or None
    actor1 = (event.actor1 or "unknown actor").title()
    actor2 = (event.actor2 or "").title()
    slug_title = title_from_url(event.source_url)
    if slug_title:
        title = f"{slug_title} [{label}]"
    else:
        title = f"{actor1} - {label}" + (f" - {actor2}" if actor2 else "") + (f" ({location})" if location else "")
    countries = [c for c in (event.country, event.actor1_country, event.actor2_country) if c]
    sectors = detect_sectors(f"{slug_title or ''} {event.source_url} {label}")
    corroborated = True
    if slug_title:
        text_type = classify_text_or_none(slug_title)
        if text_type in ("maritime_incident", "port_closure", "infrastructure", "trade", "sanctions"):
            event_type = text_type
        elif event_type in ("conflict", "sanctions") and text_type not in ("conflict", "sanctions"):
            # GDELT coded a fight / sanction but the headline has no such language (idioms, sport, celebrity "fights")
            corroborated = False
            severity = "low"
        if corroborated:
            severity = severity_from_text(slug_title, severity)  # chokepoints, pipelines, sanctions in the headline raise the floor
        countries = [*countries, *(c for c in detect_countries(slug_title) if c not in countries and c != "EU")]
    market, supply = impact_assessment(event_type, sectors, countries)
    confidence = min(0.95, 0.35 + 0.05 * min(event.sources, 6) + 0.003 * min(event.mentions, 100))
    if not corroborated:
        if event.mentions < 2 * min_mentions:
            return None  # thinly covered and the headline disagrees with the coding - almost always noise
        confidence = round(confidence * 0.6, 2)
    return EventDraft(
        event_type=event_type,
        title=title[:300],
        description=f"CAMEO {event.event_code} ({label}); Goldstein {event.goldstein:+.1f}; {event.mentions} mentions in {event.sources} source(s); tone {event.tone:+.1f}. Source: {event.source_url}",
        event_date=event.added or event.event_date,
        source="gdelt_events",
        source_id=event.global_event_id,
        source_urls=[event.source_url],
        severity=severity,
        confidence=round(confidence, 2),
        country_primary=event.country,
        country_secondary=next((c for c in (event.actor1_country, event.actor2_country) if c and c != event.country), None),
        region=location,
        lat=event.lat,
        lon=event.lon,
        keywords=[f"cameo:{event.event_code}", label, *(a for a in (event.actor1, event.actor2) if a)],
        sectors=sectors,
        affected_countries=sorted(set(countries)),
        goldstein=event.goldstein,
        mentions=event.mentions,
        market_impact=market,
        supply_chain_impact=supply,
    )


# --------------------------------------------------------- articles / feeds
def draft_from_article(title: str, url: str, seen: datetime, source: str, topic_type: str | None = None, domain: str | None = None, base_confidence: float = 0.5) -> EventDraft:
    event_type = topic_type or classify_text(title)
    countries = detect_countries(title)
    sectors = detect_sectors(title)
    severity = severity_from_text(title, "medium" if event_type in ("sanctions", "maritime_incident", "port_closure", "infrastructure") else "low")
    market, supply = impact_assessment(event_type, sectors, countries)
    return EventDraft(
        event_type=event_type,
        title=title[:300],
        description=f"{title}. Source: {domain or source} - {url}",
        event_date=seen,
        source=source,
        source_id=url[:120],
        source_urls=[url],
        severity=severity,
        confidence=base_confidence,
        country_primary=countries[0] if countries else None,
        country_secondary=countries[1] if len(countries) > 1 else None,
        keywords=[w for w in re.findall(r"[A-Za-z][A-Za-z-]{3,}", title)][:12],
        sectors=sectors,
        affected_countries=countries,
        market_impact=market,
        supply_chain_impact=supply,
    )


# ------------------------------------------------------------ correlation
ASSET_SECTORS = {"OIL": "energy", "BRENT": "energy", "NATGAS": "energy", "TTF": "energy", "GOLD": "finance", "COPPER": "trade", "BTC": "finance", "ETH": "finance"}


def relevance(event_sectors: list[str], event_countries: list[str], event_type: str, signal: dict) -> tuple[float, list[str]]:
    """Score 0-1 how related a signal is to an event: shared sector, country, or sanctions theme."""
    score, keys = 0.0, []
    sector = signal.get("sector")
    if sector and sector in event_sectors:
        score += 0.45
        keys.append(f"sector:{sector}")
    shared = set(event_countries) & set(signal.get("countries") or [])
    if shared:
        score += 0.35
        keys.extend(f"country:{c}" for c in sorted(shared))
    if event_type == "sanctions" and signal.get("kind") in ("sanctions_breach", "sanctions_update"):
        score += 0.4
        keys.append("theme:sanctions")
    if event_type in ("maritime_incident", "port_closure") and signal.get("kind") in ("evasion_event", "transshipment", "sanctions_breach"):
        score += 0.3
        keys.append("theme:maritime")
    return min(1.0, score), keys


def time_score(event_time: datetime, signal_time: datetime, window_hours: float) -> float:
    delta_hours = abs((signal_time - event_time).total_seconds()) / 3600
    if delta_hours > window_hours:
        return 0.0
    return 1 - delta_hours / window_hours
