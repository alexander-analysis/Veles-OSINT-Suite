"""Generic RSS 2.0 / Atom reader plus the OFAC "Recent Actions" page parser.

No feedparser dependency: the handful of feeds VELES reads (gov.uk, UN press,
state media, SEC/DOJ) are well-formed enough for ElementTree with a few
tolerant fallbacks.
"""

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import httpx

from app.utils.logger import logger

log = logger.bind(component="feeds")

UA = {"User-Agent": "VELES-OSINT/1.0 (research feed reader)"}
ATOM = "{http://www.w3.org/2005/Atom}"
DC = "{http://purl.org/dc/elements/1.1/}"
TAG_RE = re.compile(r"<[^>]+>")


@dataclass
class FeedItem:
    title: str
    link: str
    published: datetime | None
    summary: str
    source: str
    guid: str


def _clean(text: str | None) -> str:
    return re.sub(r"\s+", " ", TAG_RE.sub(" ", text or "")).strip()


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    value = value.strip()
    for parser in (lambda v: parsedate_to_datetime(v), lambda v: datetime.fromisoformat(v.replace("Z", "+00:00"))):
        try:
            parsed = parser(value)
            if parsed.tzinfo is not None:
                parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
            return parsed
        except (TypeError, ValueError, IndexError):
            continue
    return None


def parse_feed(xml_text: str, source: str) -> list[FeedItem]:
    root = ET.fromstring(xml_text.encode("utf-8") if isinstance(xml_text, str) else xml_text)
    items: list[FeedItem] = []
    if root.tag == f"{ATOM}feed":
        for entry in root.findall(f"{ATOM}entry"):
            link_el = entry.find(f"{ATOM}link[@rel='alternate']")
            if link_el is None:
                link_el = entry.find(f"{ATOM}link")
            link = link_el.get("href", "") if link_el is not None else ""
            items.append(
                FeedItem(
                    title=_clean(entry.findtext(f"{ATOM}title")),
                    link=link,
                    published=_parse_date(entry.findtext(f"{ATOM}published") or entry.findtext(f"{ATOM}updated")),
                    summary=_clean(entry.findtext(f"{ATOM}summary") or entry.findtext(f"{ATOM}content"))[:1000],
                    source=source,
                    guid=(entry.findtext(f"{ATOM}id") or link)[:200],
                )
            )
    else:
        for item in root.iter("item"):
            link = (item.findtext("link") or "").strip()
            items.append(
                FeedItem(
                    title=_clean(item.findtext("title")),
                    link=link,
                    published=_parse_date(item.findtext("pubDate") or item.findtext(f"{DC}date")),
                    summary=_clean(item.findtext("description"))[:1000],
                    source=source,
                    guid=(item.findtext("guid") or link)[:200],
                )
            )
    return [i for i in items if i.title]


async def fetch_feed(url: str, source: str, timeout: float = 30) -> list[FeedItem]:
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers=UA) as client:
        response = await client.get(url)
        response.raise_for_status()
    items = parse_feed(response.text, source)
    log.debug("{}: {} items", source, len(items))
    return items


OFAC_ACTION_RE = re.compile(r'href="(/recent-actions/(\d{8}))"[^>]*>(.*?)</a>', re.S)


def parse_ofac_recent_actions(html: str) -> list[FeedItem]:
    """OFAC publishes recent actions as an HTML list (no RSS any more)."""
    items = []
    for path, day, title_html in OFAC_ACTION_RE.findall(html):
        title = _clean(title_html)
        if not title:
            continue
        items.append(
            FeedItem(
                title=title,
                link=f"https://ofac.treasury.gov{path}",
                published=datetime.strptime(day, "%Y%m%d"),
                summary=title,
                source="ofac_recent_actions",
                guid=f"ofac:{day}:{title[:80]}",
            )
        )
    return items


async def fetch_ofac_recent_actions() -> list[FeedItem]:
    async with httpx.AsyncClient(timeout=30, follow_redirects=True, headers=UA) as client:
        response = await client.get("https://ofac.treasury.gov/recent-actions")
        response.raise_for_status()
    return parse_ofac_recent_actions(response.text)
