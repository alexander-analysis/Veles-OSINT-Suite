"""Domain / IP footprinting (keyless): RDAP via rdap.org, certificate transparency via crt.sh, DNS via the resolver."""

import asyncio
import re
import socket
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import httpx

from app.utils.logger import logger

log = logger.bind(component="infra")

UA = {"User-Agent": "VELES-OSINT/1.0 (sanctions research)", "Accept": "application/rdap+json, application/json"}
MIN_INTERVAL = 1.5
_last_call = 0.0
_lock = asyncio.Lock()
DOMAIN_RE = re.compile(r"(?:https?://)?(?:www\.)?([a-z0-9][a-z0-9-]{0,62}(?:\.[a-z0-9][a-z0-9-]{0,62})+)", re.I)


@dataclass
class DomainRecord:
    domain: str
    registrar: str | None = None
    registered_at: datetime | None = None
    expires_at: datetime | None = None
    nameservers: list[str] = field(default_factory=list)
    status: list[str] = field(default_factory=list)
    resolves_to: list[str] = field(default_factory=list)
    certificate_names: list[str] = field(default_factory=list)
    certificate_count: int = 0
    asn: str | None = None
    asn_org: str | None = None
    hosting_country: str | None = None
    is_live: bool | None = None
    notes: list[str] = field(default_factory=list)


def extract_domains(text: str | None) -> list[str]:
    """Domains mentioned in OFAC 'Website www.example.com' remarks."""
    if not text:
        return []
    found = []
    for m in re.finditer(r"Website\s+([^;,\s]+)", text, re.I):
        candidate = m.group(1).strip().rstrip(".").lower()
        d = DOMAIN_RE.search(candidate)
        if d and d.group(1) not in found:
            found.append(d.group(1))
    return found


def _rdap_date(events: list[dict[str, Any]], action: str) -> datetime | None:
    for event in events or []:
        if event.get("eventAction") == action and event.get("eventDate"):
            try:
                return datetime.fromisoformat(event["eventDate"].replace("Z", "+00:00")).replace(tzinfo=None)
            except ValueError:
                return None
    return None


async def _get(url: str, params: dict[str, Any] | None = None, timeout: float = 30) -> httpx.Response | None:
    global _last_call
    async with _lock:
        wait = MIN_INTERVAL - (time.monotonic() - _last_call)
        if wait > 0:
            await asyncio.sleep(wait)
        try:
            async with httpx.AsyncClient(timeout=timeout, headers=UA, follow_redirects=True) as client:
                response = await client.get(url, params=params)
        except httpx.HTTPError as exc:
            log.debug("{} failed: {}", url, exc)
            response = None
        _last_call = time.monotonic()
    return response


async def rdap_domain(domain: str) -> dict[str, Any]:
    response = await _get(f"https://rdap.org/domain/{domain}")
    if response is None or response.status_code != 200:
        return {}
    data = response.json()
    registrar = None
    for entity in data.get("entities") or []:
        if "registrar" in (entity.get("roles") or []):
            for item in (entity.get("vcardArray") or [None, []])[1]:
                if item and item[0] == "fn":
                    registrar = item[3]
    return {
        "registrar": registrar,
        "registered_at": _rdap_date(data.get("events"), "registration"),
        "expires_at": _rdap_date(data.get("events"), "expiration"),
        "nameservers": [ns.get("ldhName", "").lower() for ns in data.get("nameservers") or [] if ns.get("ldhName")],
        "status": data.get("status") or [],
    }


async def rdap_ip(ip: str) -> dict[str, Any]:
    response = await _get(f"https://rdap.org/ip/{ip}")
    if response is None or response.status_code != 200:
        return {}
    data = response.json()
    org = None
    for entity in data.get("entities") or []:
        for item in (entity.get("vcardArray") or [None, []])[1]:
            if item and item[0] == "fn" and not org:
                org = item[3]
    asn = None
    for key in ("arin_originas0_originautnums",):
        values = data.get(key)
        if values:
            asn = f"AS{values[0]}"
    return {"asn": asn, "asn_org": org, "country": (data.get("country") or "").upper() or None, "name": data.get("name")}


async def crt_names(domain: str, limit: int = 200) -> tuple[int, list[str]]:
    response = await _get("https://crt.sh/", params={"q": f"%.{domain}", "output": "json"}, timeout=60)
    if response is None or response.status_code != 200 or not response.text.strip().startswith("["):
        return 0, []
    names: set[str] = set()
    rows = response.json()
    for row in rows:
        for name in (row.get("name_value") or "").split("\n"):
            name = name.strip().lower().lstrip("*.")
            if name.endswith(domain):
                names.add(name)
    return len(rows), sorted(names)[:limit]


def resolve(domain: str) -> list[str]:
    try:
        infos = socket.getaddrinfo(domain, None, proto=socket.IPPROTO_TCP)
    except (socket.gaierror, UnicodeError, OSError):
        return []
    return sorted({info[4][0] for info in infos})


async def footprint(domain: str) -> DomainRecord:
    record = DomainRecord(domain=domain)
    rdap = await rdap_domain(domain)
    record.registrar = rdap.get("registrar")
    record.registered_at = rdap.get("registered_at")
    record.expires_at = rdap.get("expires_at")
    record.nameservers = rdap.get("nameservers", [])
    record.status = rdap.get("status", [])
    record.resolves_to = await asyncio.to_thread(resolve, domain)
    record.is_live = bool(record.resolves_to)
    if record.resolves_to:
        ip_info = await rdap_ip(record.resolves_to[0])
        record.asn, record.asn_org, record.hosting_country = ip_info.get("asn"), ip_info.get("asn_org"), ip_info.get("country")
    record.certificate_count, record.certificate_names = await crt_names(domain)
    return record
