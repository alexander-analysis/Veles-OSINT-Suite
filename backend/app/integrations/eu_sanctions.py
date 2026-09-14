"""EU consolidated financial sanctions list (FSF) importer - XML, public token.

Some ``enterprise`` subjects carry an ``identification`` of type ``imo`` -
usually an IMO *company* number, so the subject type is kept as-is.  Note: the EU "shadow fleet" port-access bans (Reg. 833/2014
Annex XLII) are *not* in this list - they are published only in the Official
Journal.
"""

import xml.etree.ElementTree as ET
from datetime import datetime

import httpx

from app.integrations.sanctions_common import SanctionedEntityRecord
from app.utils.logger import logger

log = logger.bind(component="maritime")

URL = "https://webgate.ec.europa.eu/fsd/fsf/public/files/xmlFullSanctionsList_1_1/content?token=dG9rZW4tMjAxNw"
SOURCE_URL = "https://data.europa.eu/data/datasets/consolidated-list-of-persons-groups-and-entities-subject-to-eu-financial-sanctions"
NS = {"e": "http://eu.europa.ec/fpi/fsd/export"}
TYPE_MAP = {"person": "person", "enterprise": "company"}


def _date(value: str | None) -> datetime | None:
    try:
        return datetime.strptime(value[:10], "%Y-%m-%d") if value else None
    except ValueError:
        return None


def parse_eu(xml_bytes: bytes) -> list[SanctionedEntityRecord]:
    root = ET.fromstring(xml_bytes)
    records = []
    for entity in root.findall("e:sanctionEntity", NS):
        names = [alias.get("wholeName", "").strip() for alias in entity.findall("e:nameAlias", NS)]
        names = [n for n in names if n]
        if not names:
            continue
        strong = [a.get("wholeName", "").strip() for a in entity.findall("e:nameAlias", NS) if a.get("strong") == "true"]
        name = (strong or names)[0]
        subject = entity.find("e:subjectType", NS)
        entity_type = TYPE_MAP.get(subject.get("code") if subject is not None else "", "company")
        imo = None
        for ident in entity.findall("e:identification", NS):
            if ident.get("identificationTypeCode") == "imo":
                imo = (ident.get("number") or "").strip() or None
        regulations = entity.findall("e:regulation", NS)
        programs = sorted({r.get("programme") for r in regulations if r.get("programme")})
        dates = [d for d in (_date(r.get("publicationDate")) for r in regulations) if d]
        countries = [c.get("countryIso2Code") for c in entity.findall("e:citizenship", NS) if c.get("countryIso2Code")]
        addresses = []
        for address in entity.findall("e:address", NS):
            parts = [address.get(k) for k in ("street", "city", "countryDescription") if address.get(k)]
            if parts:
                addresses.append(", ".join(parts))
            if address.get("countryIso2Code") and address.get("countryIso2Code") != "00":
                countries.append(address.get("countryIso2Code"))
        remark = (entity.findtext("e:remark", default="", namespaces=NS) or "").strip() or None
        url = next((r.findtext("e:publicationUrl", default="", namespaces=NS) for r in regulations), "") or SOURCE_URL
        records.append(
            SanctionedEntityRecord(
                authority="EU",
                source_id=entity.get("euReferenceNumber") or entity.get("logicalId"),
                name=name,
                entity_type=entity_type,
                programs=programs,
                aliases=[n for n in names if n != name],
                country=countries[0] if countries else None,
                designation_date=min(dates) if dates else None,
                imo=imo,
                addresses=addresses,
                remarks=remark,
                source_url=url,
            )
        )
    return records


async def load_eu_list() -> list[SanctionedEntityRecord]:
    async with httpx.AsyncClient(timeout=180, follow_redirects=True) as client:
        response = await client.get(URL)
        response.raise_for_status()
    records = parse_eu(response.content)
    log.info("EU FSF: {} entities ({} vessels)", len(records), sum(r.entity_type == "vessel" for r in records))
    return records
