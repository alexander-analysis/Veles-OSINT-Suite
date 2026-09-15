"""Port State Control sources (keyless): Paris MoU THETIS public REST (current detentions, bans), Tokyo MoU APCIS monthly detention list."""

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import httpx

from app.data.countries import country_to_iso
from app.utils.logger import logger

log = logger.bind(component="psc")

THETIS = "https://portal.emsa.europa.eu/o/portlet-public/rest"
APCIS = "https://apcis.tmou.org/isss/public_apcis.php?Mode=DetList"
UA = {"User-Agent": "VELES-OSINT/1.0 (port state control monitoring)", "Accept": "application/json, text/html"}


@dataclass
class PscRecord:
    source: str
    source_id: str
    event_type: str  # detention, ban
    imo: str | None
    ship_name: str
    flag: str | None
    ship_type: str | None
    port: str | None
    port_country: str | None
    event_date: datetime | None
    release_date: datetime | None = None
    company: str | None = None
    class_society: str | None = None
    gross_tonnage: float | None = None
    year_built: int | None = None
    deficiencies: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)


def _date(value: str | None) -> datetime | None:
    if not value:
        return None
    for fmt in ("%d/%m/%Y", "%d.%m.%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value.strip()[:10], fmt)
        except ValueError:
            continue
    return None


def _iso(country: dict[str, Any] | None, fallback_name: str | None = None) -> str | None:
    if country and country.get("code") and len(country["code"]) == 2:
        return country["code"].upper()
    name = (country or {}).get("description") or fallback_name
    return country_to_iso(name) if name else None


def parse_thetis_detentions(rows: list[dict[str, Any]]) -> list[PscRecord]:
    out = []
    for r in rows:
        port = r.get("detentionPort") or {}
        out.append(
            PscRecord(
                source="paris_mou",
                source_id=str(r.get("id") or f"{r.get('imoNumber')}:{r.get('detentionDate')}"),
                event_type="detention",
                imo=(str(r.get("imoNumber") or "").strip() or None),
                ship_name=(r.get("shipName") or "").strip()[:200],
                flag=_iso(r.get("flag")),
                ship_type=((r.get("shipType") or {}).get("description") or "")[:100] or None,
                port=(port.get("name") or "")[:200] or None,
                port_country=_iso(port.get("country")),
                event_date=_date(r.get("detentionDate")),
                details={"reporting_authority": ((r.get("detentionReportingAuthority") or {}).get("description")), "tanker": (r.get("shipType") or {}).get("tanker")},
            )
        )
    return out


def parse_thetis_bans(rows: list[dict[str, Any]]) -> list[PscRecord]:
    out = []
    for r in rows:
        company = r.get("ismCompany") or {}
        out.append(
            PscRecord(
                source="paris_mou",
                source_id=f"ban:{r.get('id') or r.get('imoNumber')}",
                event_type="ban",
                imo=(str(r.get("imoNumber") or "").strip() or None),
                ship_name=(r.get("shipName") or "").strip()[:200],
                flag=_iso(r.get("flag")),
                ship_type=((r.get("shipType") or {}).get("description") or "")[:100] or None,
                port=None,
                port_country=None,
                event_date=_date(r.get("banDate") or r.get("startDate") or r.get("date")),
                company=(company.get("name") or "")[:300] or None,
                details={"ban_reason": r.get("banReason") or r.get("reason"), "ban_type": r.get("banType") or r.get("type"), "company_imo": company.get("imoNumber")},
            )
        )
    return out


async def fetch_paris(limit: int = 500) -> tuple[list[PscRecord], list[PscRecord]]:
    async with httpx.AsyncClient(timeout=60, headers=UA, follow_redirects=True) as client:
        detentions = await client.get(f"{THETIS}/detention/getCurrentDetentions.json", params={"page": 1, "start": 0, "limit": limit})
        detentions.raise_for_status()
        bans = await client.get(f"{THETIS}/ban/getBanShips.json", params={"page": 1, "start": 0, "limit": limit})
        bans.raise_for_status()
    return parse_thetis_detentions(detentions.json().get("results") or []), parse_thetis_bans(bans.json().get("results") or [])


ROW_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)
CELL_RE = re.compile(r"<td[^>]*>(.*?)</td>", re.S)
TAG_RE = re.compile(r"<[^>]+>")


def parse_apcis(html: str) -> list[PscRecord]:
    """The APCIS detention list is an HTML table: #, IMO, name, flag, built, GT, type, class, ROs, company, place, detained, released, deficiencies."""
    out = []
    for row in ROW_RE.findall(html):
        raw_cells = CELL_RE.findall(row)
        if len(raw_cells) < 13:
            continue
        cells = [re.sub(r"\s+", " ", TAG_RE.sub(" ", c)).strip() for c in raw_cells]
        if not re.fullmatch(r"\d{7}", cells[1]):
            continue
        deficiencies = [d.strip() for d in re.split(r"<br\s*/?>|\n", raw_cells[13]) if TAG_RE.sub("", d).strip()] if len(raw_cells) > 13 else []
        deficiencies = [re.sub(r"\s+", " ", TAG_RE.sub(" ", d)).strip() for d in deficiencies]
        place = cells[10]
        country = country_to_iso(place.split(",")[-1].strip()) if "," in place else None
        try:
            year = int(cells[4][:4]) if cells[4][:4].isdigit() else None
        except ValueError:
            year = None
        gt = re.sub(r"[^\d.]", "", cells[5])
        out.append(
            PscRecord(
                source="tokyo_mou",
                source_id=f"{cells[1]}:{cells[11]}",
                event_type="detention",
                imo=cells[1],
                ship_name=cells[2][:200],
                flag=country_to_iso(cells[3]),
                ship_type=cells[6][:100] or None,
                port=place.split(",")[0].strip()[:200] or None,
                port_country=country,
                event_date=_date(cells[11]),
                release_date=_date(cells[12]),
                company=cells[9][:300] or None,
                class_society=cells[7][:200] or None,
                gross_tonnage=float(gt) if gt else None,
                year_built=year,
                deficiencies=deficiencies[:40],
                details={"related_ros": cells[8], "flag_name": cells[3]},
            )
        )
    return out


async def fetch_tokyo(year: int, month: int) -> list[PscRecord]:
    data = {"Mode": "DetList", "MOU": "TMOU", "Auth": "", "Src": "online", "Type": "Auth", "Month": f"{month:02d}", "Year": str(year), "SaveFile": ""}
    async with httpx.AsyncClient(timeout=120, headers={**UA, "Accept": "text/html"}, follow_redirects=True) as client:
        response = await client.post(APCIS, data=data)
        response.raise_for_status()
    records = parse_apcis(response.text)
    log.debug("tokyo mou {}-{:02d}: {} detentions", year, month, len(records))
    return records
