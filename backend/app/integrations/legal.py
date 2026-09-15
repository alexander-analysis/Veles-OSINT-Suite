"""Legal / regulatory sources (keyless): CourtListener v4 search, OFAC civil penalties page, DOJ press releases."""

import asyncio
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import httpx

from app.integrations.feeds import FeedItem, fetch_feed
from app.utils.logger import logger

log = logger.bind(component="legal")

COURTLISTENER = "https://www.courtlistener.com/api/rest/v4/search/"
OFAC_PENALTIES = "https://ofac.treasury.gov/civil-penalties-and-enforcement-information"
DOJ_RSS = "https://www.justice.gov/news/rss"
UA = {"User-Agent": "VELES-OSINT/1.0 (sanctions research)"}
MIN_INTERVAL = 2.0  # CourtListener anonymous tier: be gentle
_last_call = 0.0
_lock = asyncio.Lock()


@dataclass
class LegalRecord:
    source: str
    source_id: str
    title: str
    url: str | None
    court: str | None
    event_date: datetime | None
    event_type: str
    summary: str | None = None
    penalty_usd: float | None = None
    parties: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)


def _date(value: str | None) -> datetime | None:
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(value[:10], fmt)
        except ValueError:
            continue
    return None


async def _get(url: str, params: dict[str, Any] | None = None) -> httpx.Response | None:
    global _last_call
    async with _lock:
        wait = MIN_INTERVAL - (time.monotonic() - _last_call)
        if wait > 0:
            await asyncio.sleep(wait)
        try:
            async with httpx.AsyncClient(timeout=40, headers=UA, follow_redirects=True) as client:
                response = await client.get(url, params=params)
        except httpx.HTTPError as exc:
            log.debug("{} failed: {}", url, exc)
            response = None
        _last_call = time.monotonic()
    return response


def parse_courtlistener(data: dict[str, Any], query: str) -> list[LegalRecord]:
    out = []
    for r in data.get("results") or []:
        docket_id = r.get("docket_id") or r.get("cluster_id")
        if not docket_id:
            continue
        out.append(
            LegalRecord(
                source="courtlistener",
                source_id=str(docket_id),
                title=(r.get("caseName") or r.get("caseNameFull") or "")[:500],
                url=f"https://www.courtlistener.com{r.get('docket_absolute_url') or r.get('absolute_url') or ''}",
                court=r.get("court"),
                event_date=_date(r.get("dateFiled")),
                event_type="docket",
                summary=" - ".join(filter(None, [r.get("docketNumber"), r.get("suitNature"), r.get("cause")]))[:1000] or None,
                parties=[p for p in (r.get("party") or []) if isinstance(p, str)][:40],
                details={"query": query, "court_id": r.get("court_id"), "assigned_to": r.get("assignedTo")},
            )
        )
    return out


async def search_courtlistener(query: str, result_type: str = "r") -> list[LegalRecord]:
    """RECAP dockets ('r') or opinions ('o') mentioning the exact phrase."""
    response = await _get(COURTLISTENER, {"q": f'"{query}"', "type": result_type, "order_by": "dateFiled desc"})
    if response is None or response.status_code != 200:
        if response is not None and response.status_code == 429:
            log.warning("courtlistener rate limited")
        return []
    return parse_courtlistener(response.json(), query)


ROW_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)
CELL_RE = re.compile(r"<td[^>]*>(.*?)</td>", re.S)
TAG_RE = re.compile(r"<[^>]+>")


def parse_ofac_penalties(html: str) -> list[LegalRecord]:
    out = []
    for row in ROW_RE.findall(html):
        cells = [re.sub(r"\s+", " ", TAG_RE.sub(" ", c)).strip() for c in CELL_RE.findall(row)]
        if len(cells) < 4 or not re.match(r"\d{2}/\d{2}/\d{4}", cells[0]):
            continue
        link = re.search(r'href="([^"]+)"', row)
        amount = re.sub(r"[^\d.]", "", cells[3])
        date = _date(cells[0])
        out.append(
            LegalRecord(
                source="ofac_enforcement",
                source_id=f"{cells[0]}:{cells[1][:80]}",
                title=f"OFAC enforcement: {cells[1]} ({cells[0]})",
                url=f"https://ofac.treasury.gov{link.group(1)}" if link and link.group(1).startswith("/") else (link.group(1) if link else OFAC_PENALTIES),
                court="OFAC",
                event_date=date,
                event_type="enforcement",
                summary=f"{cells[2]} penalt(ies)/settlement(s), total USD {cells[3]}",
                penalty_usd=float(amount) if amount else None,
                parties=[cells[1]],
            )
        )
    return out


async def fetch_ofac_penalties() -> list[LegalRecord]:
    response = await _get(OFAC_PENALTIES)
    if response is None or response.status_code != 200:
        return []
    return parse_ofac_penalties(response.text)


def doj_item_to_record(item: FeedItem) -> LegalRecord:
    lowered = f"{item.title} {item.summary}".lower()
    kind = "indictment" if any(w in lowered for w in ("indict", "charged", "arrested", "extradit")) else "settlement" if any(w in lowered for w in ("settle", "plead", "sentenced", "forfeit", "penalty")) else "press_release"
    return LegalRecord(source="doj", source_id=(item.guid or item.link)[:200], title=item.title[:500], url=item.link, court="US DOJ", event_date=item.published, event_type=kind, summary=item.summary[:1000] or None)


async def fetch_doj(keywords: tuple[str, ...] = ("sanction", "export control", "ofac", "money launder", "iran", "russia", "north korea", "oil", "tanker", "crypto", "evasion")) -> list[LegalRecord]:
    items = await fetch_feed(DOJ_RSS, "doj")
    out = []
    for item in items:
        text = f"{item.title} {item.summary}".lower()
        if any(k in text for k in keywords):
            out.append(doj_item_to_record(item))
    return out
