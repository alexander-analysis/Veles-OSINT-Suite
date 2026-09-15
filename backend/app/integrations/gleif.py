"""GLEIF Legal Entity Identifier API (keyless): entity search, records, ownership relationships.

https://api.gleif.org/api/v1 - JSON:API. Polite pacing (~1 request/s); the
service publishes no hard limit but VELES is a background walker, not a crawler.
"""

import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import httpx

from app.utils.logger import logger

log = logger.bind(component="gleif")

BASE = "https://api.gleif.org/api/v1"
HEADERS = {"Accept": "application/vnd.api+json", "User-Agent": "VELES-OSINT/1.0 (sanctions research)"}
MIN_INTERVAL = 1.0
_last_call = 0.0
_lock = asyncio.Lock()


@dataclass
class LeiRecord:
    lei: str
    name: str
    other_names: list[str]
    country: str | None
    jurisdiction: str | None
    status: str | None  # ACTIVE / INACTIVE
    registration_status: str | None  # ISSUED / LAPSED / RETIRED / ...
    category: str | None
    legal_form: str | None
    creation_date: datetime | None
    address: str | None
    city: str | None
    headquarters_country: str | None = None
    raw_relationships: dict[str, Any] = field(default_factory=dict)


@dataclass
class ReportingException:
    category: str
    reason: str  # NO_KNOWN_PERSON, NATURAL_PERSONS, NON_CONSOLIDATING, NO_LEI, NON_PUBLIC, ...


async def _get(path: str, params: dict[str, Any] | None = None) -> httpx.Response:
    global _last_call
    async with _lock:
        wait = MIN_INTERVAL - (time.monotonic() - _last_call)
        if wait > 0:
            await asyncio.sleep(wait)
        async with httpx.AsyncClient(timeout=30, headers=HEADERS) as client:
            response = await client.get(f"{BASE}/{path}", params=params)
        _last_call = time.monotonic()
    return response


def _date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def parse_record(item: dict[str, Any]) -> LeiRecord:
    attrs = item.get("attributes", {})
    entity = attrs.get("entity", {})
    legal = entity.get("legalAddress", {}) or {}
    hq = entity.get("headquartersAddress", {}) or {}
    others = [n.get("name") for n in entity.get("otherNames", []) or [] if n.get("name")]
    others += [n.get("name") for n in entity.get("transliteratedOtherNames", []) or [] if n.get("name")]
    form = entity.get("legalForm") or {}
    return LeiRecord(
        lei=attrs.get("lei") or item.get("id"),
        name=(entity.get("legalName") or {}).get("name", ""),
        other_names=others,
        country=legal.get("country"),
        jurisdiction=entity.get("jurisdiction"),
        status=entity.get("status"),
        registration_status=(attrs.get("registration") or {}).get("status"),
        category=entity.get("category"),
        legal_form=form.get("other") or form.get("id"),
        creation_date=_date(entity.get("creationDate")),
        address=", ".join(filter(None, [*(legal.get("addressLines") or []), legal.get("postalCode")])) or None,
        city=legal.get("city"),
        headquarters_country=hq.get("country"),
        raw_relationships={k: bool(v.get("links")) for k, v in (item.get("relationships") or {}).items() if isinstance(v, dict)},
    )


async def search(name: str, limit: int = 10, fulltext: bool = False) -> list[LeiRecord]:
    """Entities whose legal name matches ``name`` (``*`` wildcards allowed); ``fulltext`` also searches other names."""
    key = "filter[fulltext]" if fulltext else "filter[entity.legalName]"
    response = await _get("lei-records", {key: name, "page[size]": limit})
    if response.status_code != 200:
        log.debug("search {} -> {}", name, response.status_code)
        return []
    return [parse_record(item) for item in response.json().get("data", [])]


async def record(lei: str) -> LeiRecord | None:
    response = await _get(f"lei-records/{lei}")
    if response.status_code != 200:
        return None
    return parse_record(response.json()["data"])


async def parent(lei: str, ultimate: bool = False) -> LeiRecord | ReportingException | None:
    """Direct or ultimate accounting-consolidation parent, or the reporting exception explaining why there is none."""
    kind = "ultimate-parent" if ultimate else "direct-parent"
    response = await _get(f"lei-records/{lei}/{kind}")
    if response.status_code == 200 and response.json().get("data"):
        return parse_record(response.json()["data"])
    exception = await _get(f"lei-records/{lei}/{kind}-reporting-exception")
    if exception.status_code == 200 and exception.json().get("data"):
        attrs = exception.json()["data"].get("attributes", {})
        return ReportingException(category=attrs.get("category", ""), reason=attrs.get("reason", ""))
    return None


async def children(lei: str, limit: int = 50, ultimate: bool = False) -> list[LeiRecord]:
    kind = "ultimate-children" if ultimate else "direct-children"
    response = await _get(f"lei-records/{lei}/{kind}", {"page[size]": min(limit, 200)})
    if response.status_code != 200:
        return []
    return [parse_record(item) for item in response.json().get("data", [])]
