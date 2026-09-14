"""UN Security Council Consolidated List importer (XML, public).

Individuals and entities are listed per committee (``UN_LIST_TYPE``: DPRK,
Iran, Libya, ...).  IMO numbers quoted in ``COMMENTS1`` are usually IMO *company* numbers of
shipping operators; they are kept on the record but do not change its type.
"""

import xml.etree.ElementTree as ET
from datetime import datetime

import httpx

from app.data.countries import country_to_iso
from app.integrations.sanctions_common import SanctionedEntityRecord, extract_imo
from app.utils.logger import logger

log = logger.bind(component="maritime")

URL = "https://scsanctions.un.org/resources/xml/en/consolidated.xml"
SOURCE_URL = "https://main.un.org/securitycouncil/en/content/un-sc-consolidated-list"


def _date(value: str | None) -> datetime | None:
    try:
        return datetime.strptime(value[:10], "%Y-%m-%d") if value else None
    except ValueError:
        return None


def _individual_name(node: ET.Element) -> str:
    parts = [node.findtext(tag, default="").strip() for tag in ("FIRST_NAME", "SECOND_NAME", "THIRD_NAME", "FOURTH_NAME")]
    return " ".join(p for p in parts if p)


def parse_un(xml_bytes: bytes) -> list[SanctionedEntityRecord]:
    root = ET.fromstring(xml_bytes)
    records = []
    for kind, tag, alias_tag, is_person in (("company", "ENTITY", "ENTITY_ALIAS", False), ("person", "INDIVIDUAL", "INDIVIDUAL_ALIAS", True)):
        for node in root.iter(tag):
            name = _individual_name(node) if is_person else (node.findtext("FIRST_NAME", default="") or "").strip()
            if not name:
                continue
            comments = node.findtext("COMMENTS1", default="") or ""
            imo = None if is_person else extract_imo(comments)
            aliases = [a.strip() for a in (al.findtext("ALIAS_NAME", default="") for al in node.findall(alias_tag)) if a and a.strip()]
            countries = [c.strip() for c in (n.findtext("VALUE", default="") for n in node.findall("NATIONALITY")) if c]
            addresses = []
            for addr in node.findall("ENTITY_ADDRESS") + node.findall("INDIVIDUAL_ADDRESS"):
                parts = [addr.findtext(k, default="").strip() for k in ("STREET", "CITY", "COUNTRY")]
                parts = [p for p in parts if p]
                if parts:
                    addresses.append(", ".join(parts))
                if addr.findtext("COUNTRY"):
                    countries.append(addr.findtext("COUNTRY").strip())
            committee = (node.findtext("UN_LIST_TYPE", default="") or "").strip() or None
            records.append(
                SanctionedEntityRecord(
                    authority="UN",
                    source_id=node.findtext("DATAID", default="").strip() or node.findtext("REFERENCE_NUMBER", default="").strip(),
                    name=name,
                    entity_type=kind,
                    programs=[committee] if committee else [],
                    aliases=aliases,
                    country=next((iso for iso in (country_to_iso(c) for c in countries) if iso), None),
                    designation_date=_date(node.findtext("LISTED_ON")),
                    imo=imo,
                    addresses=addresses,
                    un_committee=committee,
                    remarks=(node.findtext("REFERENCE_NUMBER", default="").strip() + ": " + comments.strip())[:1000] or None,
                    source_url=SOURCE_URL,
                )
            )
    return records


async def load_un_list() -> list[SanctionedEntityRecord]:
    async with httpx.AsyncClient(timeout=120, follow_redirects=True) as client:
        response = await client.get(URL)
        response.raise_for_status()
    records = parse_un(response.content)
    log.info("UN consolidated: {} entries ({} vessels)", len(records), sum(r.entity_type == "vessel" for r in records))
    return records
