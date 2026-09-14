"""Common record produced by every sanctions-list importer."""

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime

IMO_PATTERN = re.compile(r"\bIMO\b[^0-9]{0,40}?(\d{7})\b", re.IGNORECASE)


def normalize_name(name: str | None) -> str:
    """Upper-case ASCII, punctuation stripped, whitespace collapsed - for exact-ish matching."""
    if not name:
        return ""
    text = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    text = re.sub(r"[^A-Z0-9 ]+", " ", text.upper())
    return re.sub(r"\s+", " ", text).strip()


def extract_imo(text: str | None) -> str | None:
    if not text:
        return None
    match = IMO_PATTERN.search(text)
    return match.group(1) if match else None


@dataclass
class SanctionedEntityRecord:
    authority: str  # OFAC, EU, UN
    source_id: str
    name: str
    entity_type: str  # vessel, company, person
    programs: list[str] = field(default_factory=list)
    aliases: list[str] = field(default_factory=list)
    country: str | None = None  # ISO alpha-2
    designation_date: datetime | None = None
    imo: str | None = None
    vessel_flag: str | None = None
    vessel_owner: str | None = None
    call_sign: str | None = None
    addresses: list[str] = field(default_factory=list)
    un_committee: str | None = None
    remarks: str | None = None
    source_url: str | None = None
