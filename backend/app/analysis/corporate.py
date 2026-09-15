"""Corporate intelligence rules: name matching, shell-company indicators, ownership risk."""

import re
from dataclasses import dataclass
from datetime import datetime
from difflib import SequenceMatcher

from app.integrations.sanctions_common import normalize_name

# Legal-form suffixes that carry no identity (stripped before comparing names)
LEGAL_FORMS = {
    "LTD", "LIMITED", "LLC", "L L C", "INC", "INCORPORATED", "CORP", "CORPORATION", "CO", "COMPANY", "PLC", "GMBH", "AG", "SA", "S A", "SARL", "S A R L",
    "BV", "B V", "NV", "N V", "OOO", "OAO", "PAO", "ZAO", "AO", "JSC", "OJSC", "PJSC", "CJSC", "LLP", "LP", "PTE", "PTY", "SDN", "BHD", "SRL", "S R L", "SPA", "S P A",
    "KFT", "SP Z O O", "OY", "AB", "AS", "A S", "APS", "DAC", "FZE", "FZCO", "FZ LLC", "DMCC", "SE", "KK", "HOLDING", "HOLDINGS", "GROUP", "TRADING",
    "PUBLIC JOINT STOCK COMPANY", "JOINT STOCK COMPANY", "LIMITED LIABILITY COMPANY", "OPEN JOINT STOCK COMPANY", "CLOSED JOINT STOCK COMPANY",
}
SECRECY_JURISDICTIONS = {"VG", "KY", "PA", "MH", "LR", "SC", "BZ", "VU", "WS", "BS", "BM", "JE", "GG", "IM", "LI", "MU", "AI", "TC", "KN", "LC", "VC", "DM", "AG", "NR", "CK", "NU", "GI", "MT", "CY", "HK", "AE", "SG", "LU", "CH"}
SANCTIONS_JURISDICTIONS = {"RU", "IR", "KP", "SY", "BY", "CU", "VE", "MM"}
SHELL_NAME_HINTS = ("TRADING", "HOLDINGS", "HOLDING", "INTERNATIONAL", "GLOBAL", "MANAGEMENT", "SHIPPING", "MARINE", "MARITIME", "LOGISTICS", "GENERAL TRADING", "FZE", "FZCO", "DMCC")


def _strip_forms(tokens: list[str], from_end: bool) -> list[str]:
    changed = True
    while changed and len(tokens) > 1:
        changed = False
        for width in (4, 3, 2, 1):
            if len(tokens) <= width:
                continue
            chunk = tokens[-width:] if from_end else tokens[:width]
            if " ".join(chunk) in LEGAL_FORMS:
                tokens = tokens[:-width] if from_end else tokens[width:]
                changed = True
                break
    return tokens


def core_name(name: str | None) -> str:
    """Normalized name with legal-form tokens removed: 'Rosneft Trading S.A.' -> 'ROSNEFT'."""
    tokens = normalize_name(name).split()
    tokens = _strip_forms(tokens, from_end=True)
    tokens = _strip_forms(tokens, from_end=False)
    return " ".join(tokens)


def name_similarity(a: str | None, b: str | None) -> float:
    ca, cb = core_name(a), core_name(b)
    if not ca or not cb:
        return 0.0
    if ca == cb:
        return 1.0
    return round(SequenceMatcher(None, ca, cb).ratio(), 3)


def best_match(query: str, candidates: list[tuple[str, list[str]]], min_similarity: float = 0.9) -> tuple[int, float] | None:
    """Index and score of the candidate (name + other names) closest to ``query``."""
    best: tuple[int, float] | None = None
    for i, (name, others) in enumerate(candidates):
        score = max([name_similarity(query, name), *(name_similarity(query, o) for o in others)])
        if score >= min_similarity and (best is None or score > best[1]):
            best = (i, score)
    return best


@dataclass
class ShellAssessment:
    indicators: list[str]
    confidence: float
    is_shell: bool
    opaque: bool


def assess_shell(
    country: str | None,
    registration_status: str | None,
    entity_status: str | None,
    creation_date: datetime | None,
    parent_exception: str | None,
    name: str | None,
    children_count: int,
    now: datetime,
    linked_to_sanctioned: bool = False,
) -> ShellAssessment:
    """Score opacity / shell indicators (0-1). Not a legal finding - a prioritisation signal."""
    indicators: list[str] = []
    score = 0.0
    if country in SECRECY_JURISDICTIONS:
        indicators.append(f"secrecy_jurisdiction:{country}")
        score += 0.25
    if parent_exception in ("NO_KNOWN_PERSON", "NON_PUBLIC", "NO_LEI"):
        indicators.append(f"parent_undisclosed:{parent_exception}")
        score += 0.25
    elif parent_exception == "NATURAL_PERSONS":
        indicators.append("owned_by_natural_persons")
        score += 0.1
    if registration_status in ("LAPSED", "RETIRED", "ANNULLED"):
        indicators.append(f"lei_{registration_status.lower()}")
        score += 0.1
    if entity_status == "INACTIVE":
        indicators.append("entity_inactive")
        score += 0.05
    if creation_date and (now - creation_date).days < 365:
        indicators.append("recently_formed")
        score += 0.15
    upper = normalize_name(name)
    if any(h in upper for h in SHELL_NAME_HINTS) and country in SECRECY_JURISDICTIONS:
        indicators.append("generic_trading_name")
        score += 0.1
    if children_count == 0 and country in SECRECY_JURISDICTIONS:
        indicators.append("no_subsidiaries")
        score += 0.05
    if linked_to_sanctioned:
        indicators.append("sanctions_linked")
        score += 0.15
    confidence = round(min(score, 1.0), 2)
    opaque = any(i.startswith("parent_undisclosed") for i in indicators)
    return ShellAssessment(indicators, confidence, confidence >= 0.5, opaque)


def ownership_risk(chain: list[dict], involves_sanctioned: bool, involves_shell: bool) -> float:
    score = 0.2 + 0.05 * max(0, len(chain) - 1)
    if involves_sanctioned:
        score += 0.5
    if involves_shell:
        score += 0.15
    if any((hop.get("country") in SECRECY_JURISDICTIONS) for hop in chain):
        score += 0.1
    if any((hop.get("country") in SANCTIONS_JURISDICTIONS) for hop in chain):
        score += 0.1
    return round(min(score, 1.0), 2)


def company_risk(linked: bool, match_type: str | None, shell_confidence: float | None, country: str | None) -> float:
    score = 0.1
    if linked:
        score += {"direct": 0.9, "parent": 0.75, "ultimate_parent": 0.6, "child": 0.45, "vessel_owner": 0.8, "director": 0.6, "shareholder": 0.6}.get(match_type or "", 0.5)
    score += 0.3 * (shell_confidence or 0)
    if country in SANCTIONS_JURISDICTIONS:
        score += 0.1
    return round(min(score, 1.0), 2)


def latin_enough(name: str | None, minimum: float = 0.6) -> bool:
    """True when most letters survive ASCII folding - Cyrillic / Greek / Arabic spellings cannot be matched against Latin registries."""
    letters = [c for c in (name or "") if c.isalpha()]
    if not letters:
        return False
    folded = normalize_name(name)
    return sum(c.isalpha() for c in folded) / len(letters) >= minimum


def clean_company_name(name: str | None) -> str:
    return re.sub(r"\s+", " ", (name or "")).strip()[:300]
