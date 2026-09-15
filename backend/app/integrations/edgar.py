"""SEC EDGAR company lookup (keyless; the SEC asks for a descriptive User-Agent with a contact).

Only the ``browse-edgar`` Atom company search is used - EDGAR full-text search
now returns 403 to non-browser clients.
"""

import asyncio
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass

import httpx

from app.config import settings
from app.utils.logger import logger

log = logger.bind(component="edgar")

BROWSE_URL = "https://www.sec.gov/cgi-bin/browse-edgar"
ATOM = "{http://www.w3.org/2005/Atom}"
MIN_INTERVAL = 0.6  # SEC fair-use limit is 10 requests/s; stay far below it
_last_call = 0.0
_lock = asyncio.Lock()


@dataclass
class EdgarCompany:
    cik: str
    name: str
    sic_description: str | None
    state: str | None
    business_address: str | None
    fiscal_year_end: str | None
    filings_url: str


def _user_agent() -> str:
    contact = settings.key("EDGAR_CONTACT_EMAIL") or "veles-osint@example.org"
    return f"VELES OSINT platform {contact}"


def parse_browse_atom(xml_text: str) -> list[EdgarCompany]:
    root = ET.fromstring(xml_text.encode("utf-8", "ignore"))
    out = []
    infos = root.findall(f".//{ATOM}company-info") or root.findall(".//company-info")
    for info in infos:
        cik = (info.findtext(f"{ATOM}cik") or info.findtext("cik") or "").strip()
        name = (info.findtext(f"{ATOM}conformed-name") or info.findtext("conformed-name") or "").strip()
        if not cik or not name:
            continue
        addr = info.find(f"{ATOM}addresses/{ATOM}address[@type='business']")
        if addr is None:
            addr = info.find("addresses/address[@type='business']")
        parts = []
        if addr is not None:
            for tag in ("street1", "street2", "city", "state", "zip"):
                value = addr.findtext(f"{ATOM}{tag}") or addr.findtext(tag)
                if value:
                    parts.append(value.strip())
        out.append(
            EdgarCompany(
                cik=cik.lstrip("0") or cik,
                name=re.sub(r"\s+", " ", name),
                sic_description=(info.findtext(f"{ATOM}assigned-sic-desc") or info.findtext("assigned-sic-desc") or "").strip() or None,
                state=(info.findtext(f"{ATOM}state-location") or info.findtext("state-location") or "").strip() or None,
                business_address=", ".join(parts) or None,
                fiscal_year_end=(info.findtext(f"{ATOM}fiscal-year-end") or info.findtext("fiscal-year-end") or "").strip() or None,
                filings_url=f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}",
            )
        )
    return out


async def lookup_company(name: str, count: int = 10) -> list[EdgarCompany]:
    global _last_call
    async with _lock:
        wait = MIN_INTERVAL - (time.monotonic() - _last_call)
        if wait > 0:
            await asyncio.sleep(wait)
        async with httpx.AsyncClient(timeout=30, headers={"User-Agent": _user_agent(), "Accept": "application/atom+xml"}) as client:
            response = await client.get(BROWSE_URL, params={"action": "getcompany", "company": name, "output": "atom", "count": count, "owner": "include"})
        _last_call = time.monotonic()
    if response.status_code != 200 or "<feed" not in response.text[:500]:
        log.debug("edgar lookup {} -> {}", name, response.status_code)
        return []
    try:
        return parse_browse_atom(response.text)
    except ET.ParseError:
        return []
