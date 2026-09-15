"""Leak / breach feeds (keyless): ransomware.live recent victims, Have I Been Pwned breach catalogue."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import httpx

from app.utils.logger import logger

log = logger.bind(component="leaks")

RANSOMWARE_RECENT = "https://api.ransomware.live/v2/recentvictims"
HIBP_BREACHES = "https://haveibeenpwned.com/api/v3/breaches"
UA = {"User-Agent": "VELES-OSINT/1.0 (breach monitoring)"}


@dataclass
class BreachRecord:
    source: str
    source_id: str
    victim_name: str
    victim_domain: str | None
    country: str | None
    sector: str | None
    threat_actor: str | None
    event_date: datetime | None
    description: str | None
    url: str | None
    records_affected: int | None = None
    data_classes: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)


def _date(value: str | None) -> datetime | None:
    if not value:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(value[: len(fmt) + 7] if "%f" in fmt else value[:19], fmt)
        except ValueError:
            continue
    return None


def parse_ransomware(rows: list[dict[str, Any]]) -> list[BreachRecord]:
    out = []
    for row in rows:
        name = (row.get("victim") or row.get("post_title") or "").strip()
        if not name:
            continue
        date = _date(row.get("discovered") or row.get("attackdate") or row.get("published"))
        out.append(
            BreachRecord(
                source="ransomware_live",
                source_id=f"{row.get('group_name') or row.get('group', '?')}:{name}:{(row.get('discovered') or row.get('attackdate') or '')[:10]}"[:200],
                victim_name=name[:300],
                victim_domain=(row.get("domain") or row.get("website") or "").strip() or None,
                country=(row.get("country") or "").strip().upper()[:3] or None,
                sector=(row.get("activity") or "").strip() or None,
                threat_actor=(row.get("group_name") or row.get("group") or "").strip() or None,
                event_date=date,
                description=(row.get("description") or "").strip()[:2000] or None,
                url=row.get("claim_url") or row.get("post_url") or None,
                details={k: row.get(k) for k in ("screenshot", "infostealer") if row.get(k)},
            )
        )
    return out


def parse_hibp(rows: list[dict[str, Any]]) -> list[BreachRecord]:
    out = []
    for row in rows:
        name = row.get("Name") or row.get("Title")
        if not name:
            continue
        out.append(
            BreachRecord(
                source="hibp",
                source_id=str(name)[:200],
                victim_name=(row.get("Title") or name)[:300],
                victim_domain=(row.get("Domain") or "").strip() or None,
                country=None,
                sector=None,
                threat_actor=None,
                event_date=_date(row.get("BreachDate")),
                description=(row.get("Description") or "").strip()[:2000] or None,
                url=row.get("DisclosureUrl") or f"https://haveibeenpwned.com/PwnedWebsites#{name}",
                records_affected=row.get("PwnCount"),
                data_classes=list(row.get("DataClasses") or []),
                details={"added": row.get("AddedDate"), "verified": row.get("IsVerified"), "stealer_log": row.get("IsStealerLog"), "sensitive": row.get("IsSensitive")},
            )
        )
    return out


async def fetch_ransomware_recent() -> list[BreachRecord]:
    async with httpx.AsyncClient(timeout=40, headers=UA) as client:
        response = await client.get(RANSOMWARE_RECENT)
        response.raise_for_status()
        data = response.json()
    rows = data if isinstance(data, list) else data.get("data") or data.get("victims") or []
    return parse_ransomware(rows)


async def fetch_hibp_breaches() -> list[BreachRecord]:
    async with httpx.AsyncClient(timeout=40, headers=UA) as client:
        response = await client.get(HIBP_BREACHES)
        response.raise_for_status()
        return parse_hibp(response.json())
