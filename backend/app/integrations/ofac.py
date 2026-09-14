"""OFAC Specially Designated Nationals (SDN) list importer.

Files (public domain, no auth): ``sdn.csv`` (entities) and ``alt.csv``
(aliases).  ``sdn.csv`` has no header; columns are

    ent_num, SDN_Name, SDN_Type, Program, Title, Call_Sign, Vess_type,
    Tonnage, GRT, Vess_flag, Vess_owner, Remarks

with ``-0-`` as the null marker.  Vessel IMO numbers live in ``Remarks``
("Vessel Registration Identification IMO 9179414").
"""

import csv
import io

import httpx

from app.data.countries import country_to_iso
from app.integrations.sanctions_common import SanctionedEntityRecord, extract_imo
from app.utils.logger import logger

log = logger.bind(component="maritime")

SDN_URL = "https://www.treasury.gov/ofac/downloads/sdn.csv"
ALT_URL = "https://www.treasury.gov/ofac/downloads/alt.csv"
SOURCE_URL = "https://ofac.treasury.gov/specially-designated-nationals-and-blocked-persons-list-sdn-human-readable-lists"
TYPE_MAP = {"vessel": "vessel", "entity": "company", "individual": "person", "aircraft": "aircraft"}


def _programs(value: str | None) -> list[str]:
    """OFAC joins multiple programmes as ``A] [B] [C`` (occasionally with ``;``)."""
    if not value:
        return []
    parts = value.replace("] [", ";").replace("[", "").replace("]", "").split(";")
    return [p.strip() for p in parts if p.strip()]


def _clean(value: str | None) -> str | None:
    value = (value or "").strip()
    return None if value in ("", "-0-") else value


def parse_sdn(sdn_text: str, alt_text: str = "") -> list[SanctionedEntityRecord]:
    aliases: dict[str, list[str]] = {}
    for row in csv.reader(io.StringIO(alt_text)):
        if len(row) >= 4 and _clean(row[3]):
            aliases.setdefault(row[0].strip(), []).append(_clean(row[3]))

    records = []
    for row in csv.reader(io.StringIO(sdn_text)):
        if len(row) < 12:
            continue
        ent_num, name, sdn_type, program, _title, call_sign, vess_type, _tonnage, _grt, vess_flag, vess_owner, remarks = (
            _clean(cell) for cell in row[:12]
        )
        if not ent_num or not name:
            continue
        entity_type = TYPE_MAP.get((sdn_type or "entity").lower(), "company")
        flag = country_to_iso(vess_flag)
        records.append(
            SanctionedEntityRecord(
                authority="OFAC",
                source_id=ent_num,
                name=name,
                entity_type=entity_type,
                programs=_programs(program),
                aliases=aliases.get(ent_num, []),
                country=flag,
                imo=extract_imo(remarks),
                vessel_flag=flag,
                vessel_owner=vess_owner,
                call_sign=call_sign,
                remarks=(f"{vess_type}; " if vess_type else "") + (remarks or "") or None,
                source_url=SOURCE_URL,
            )
        )
    return records


async def load_ofac_list() -> list[SanctionedEntityRecord]:
    async with httpx.AsyncClient(timeout=120, follow_redirects=True, headers={"User-Agent": "VELES-OSINT/0.1"}) as client:
        sdn = await client.get(SDN_URL)
        sdn.raise_for_status()
        alt = await client.get(ALT_URL)
        alt.raise_for_status()
    records = parse_sdn(sdn.text, alt.text)
    log.info("OFAC SDN: {} entities ({} vessels)", len(records), sum(r.entity_type == "vessel" for r in records))
    return records
