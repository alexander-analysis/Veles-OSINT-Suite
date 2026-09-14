"""Sanctions screening: an in-memory index over active listings plus the matching rules.

Confidence ladder (brief section 17):

* IMO / MMSI match on a listed vessel                      0.95  direct_match
* Exact vessel-name match (flag agrees / unknown / differs) 0.90 / 0.80 / 0.55
* Fuzzy vessel-name match (flag agrees / unknown / differs) 0.70 / 0.50 / 0.35
* ... capped at 0.30 when both IMO numbers are known and differ (namesake)
* Owner / operator matches a listed company (+0.05 flag)   0.60  owner_match
* Beneficial owner matches a listed entity                 0.40  owner_match (review queue)
* Flag state under a comprehensive programme (IR/KP/SY/CU) 0.80  flag_violation
"""

import re
from collections import defaultdict
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Iterable

from app.integrations.sanctions_common import normalize_name
from app.utils.time import utcnow

# Jurisdictions under comprehensive (territory-wide) US sanctions programmes
COMPREHENSIVE_PROGRAMS = {"IR": "IRAN", "KP": "DPRK", "SY": "SYRIA", "CU": "CUBA"}
STOPWORDS = {"THE", "OF", "AND", "CO", "LTD", "LLC", "INC", "SA", "AO", "OOO", "COMPANY", "LIMITED", "SHIPPING", "MV", "MT"}
MATCH_LABELS = {
    "imo": "IMO", "mmsi": "MMSI", "name_exact": "name", "name_fuzzy": "name (fuzzy)",
    "owner": "owner", "operator": "operator", "beneficial_owner": "beneficial owner",
}


def severity_for_confidence(confidence: float) -> str:
    if confidence >= 0.9:
        return "critical"
    if confidence >= 0.7:
        return "high"
    if confidence >= 0.5:
        return "medium"
    return "low"


def name_similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, normalize_name(a), normalize_name(b)).ratio()


@dataclass
class IndexedEntity:
    id: int
    authority: str
    name: str
    normalized: str
    entity_type: str
    programs: list[str]
    aliases: list[str]
    imo: str | None
    mmsi: str | None
    country: str | None
    vessel_flag: str | None
    designation_date: object = None


@dataclass
class Match:
    entity: IndexedEntity | None
    match_type: str  # imo, mmsi, name_exact, name_fuzzy, owner, operator, beneficial_owner, flag_program
    matched_value: str
    confidence: float
    breach_type: str  # direct_match, owner_match, flag_violation
    authority: str
    summary: str
    similarity: float | None = None
    programs: list[str] = field(default_factory=list)

    @property
    def severity(self) -> str:
        return severity_for_confidence(self.confidence)


def _tokens(normalized: str) -> set[str]:
    return {t for t in normalized.split() if len(t) >= 3 and t not in STOPWORDS}


class SanctionsIndex:
    """Lookup structures over active listings from every authority."""

    def __init__(self, entities: Iterable) -> None:
        self.entities: dict[int, IndexedEntity] = {}
        self.by_imo: dict[str, list[int]] = defaultdict(list)
        self.by_mmsi: dict[str, list[int]] = defaultdict(list)
        self.by_name: dict[str, list[int]] = defaultdict(list)
        self.token_index: dict[str, set[int]] = defaultdict(set)
        self.built_at = utcnow()
        for row in entities:
            entity = IndexedEntity(
                id=row.id,
                authority=row.designating_authority,
                name=row.name,
                normalized=row.name_normalized or normalize_name(row.name),
                entity_type=row.entity_type or "company",
                programs=list(row.programs or []),
                aliases=list(row.aliases or []),
                imo=row.imo,
                mmsi=row.mmsi,
                country=row.country_linked,
                vessel_flag=row.vessel_flag,
                designation_date=row.designation_date,
            )
            self.entities[entity.id] = entity
            if entity.imo and entity.entity_type == "vessel":
                self.by_imo[entity.imo].append(entity.id)
            if entity.mmsi:
                self.by_mmsi[entity.mmsi].append(entity.id)
            for alias in [entity.normalized, *(normalize_name(a) for a in entity.aliases)]:
                if alias:
                    self.by_name[alias].append(entity.id)
                    for token in _tokens(alias):
                        self.token_index[token].add(entity.id)

    def __len__(self) -> int:
        return len(self.entities)

    def exact(self, name: str, entity_types: set[str] | None = None) -> list[IndexedEntity]:
        hits = [self.entities[i] for i in self.by_name.get(normalize_name(name), [])]
        return [e for e in hits if not entity_types or e.entity_type in entity_types]

    def fuzzy(self, name: str, entity_types: set[str] | None = None, min_similarity: float = 0.88, limit: int = 5) -> list[tuple[IndexedEntity, float]]:
        normalized = normalize_name(name)
        tokens = _tokens(normalized)
        if not normalized or not tokens:
            return []
        candidates: set[int] = set()
        for token in tokens:
            candidates |= self.token_index.get(token, set())
        scored = []
        for entity_id in candidates:
            entity = self.entities[entity_id]
            if entity_types and entity.entity_type not in entity_types:
                continue
            aliases = [a for a in [entity.normalized, *(normalize_name(x) for x in entity.aliases)] if a]
            best = max(SequenceMatcher(None, normalized, alias).ratio() for alias in aliases)
            if min_similarity <= best < 1.0:
                scored.append((entity, best))
        scored.sort(key=lambda item: item[1], reverse=True)
        return scored[:limit]

    # --------------------------------------------------------------- screens
    def match_name(self, name: str, entity_types: set[str] | None = None, min_similarity: float = 0.88) -> list[Match]:
        """Screen a free-text name (analyst check, or an owner/operator field)."""
        matches = [self._match(e, "name_exact", name, 0.9, "direct_match", similarity=1.0) for e in self.exact(name, entity_types)]
        seen = {m.entity.id for m in matches}
        for entity, score in self.fuzzy(name, entity_types, min_similarity):
            if entity.id not in seen:
                matches.append(self._match(entity, "name_fuzzy", name, round(0.6 + 0.3 * score, 2), "direct_match", similarity=round(score, 3)))
        return matches

    def match_vessel(self, vessel, fuzzy_min_similarity: float = 0.9) -> list[Match]:
        """Screen a ``Vessel`` (ORM object or anything with the same attributes) against every authority."""
        matches: list[Match] = []
        seen: set[tuple[int, str]] = set()

        def add(match: Match) -> None:
            key = (match.entity.id if match.entity else -1, match.match_type)
            if key not in seen:
                seen.add(key)
                matches.append(match)

        flag = getattr(vessel, "flag_state", None)
        if getattr(vessel, "imo", None):
            for entity_id in self.by_imo.get(str(vessel.imo), []):
                add(self._match(self.entities[entity_id], "imo", str(vessel.imo), 0.95, "direct_match"))
        if getattr(vessel, "mmsi", None):
            for entity_id in self.by_mmsi.get(str(vessel.mmsi), []):
                add(self._match(self.entities[entity_id], "mmsi", str(vessel.mmsi), 0.95, "direct_match"))
        if getattr(vessel, "name", None):
            vessel_imo = getattr(vessel, "imo", None)
            for entity in self.exact(vessel.name, {"vessel"}):
                confidence = self._name_confidence(entity, flag, vessel_imo, vessel.name, exact=True)
                add(self._match(entity, "name_exact", vessel.name, confidence, "direct_match", similarity=1.0))
            for entity, score in self.fuzzy(vessel.name, {"vessel"}, fuzzy_min_similarity):
                confidence = self._name_confidence(entity, flag, vessel_imo, vessel.name, exact=False)
                add(self._match(entity, "name_fuzzy", vessel.name, confidence, "direct_match", similarity=round(score, 3)))
        for attribute, match_type, base in (("owner_name", "owner", 0.6), ("registered_operator", "operator", 0.6), ("beneficial_owner", "beneficial_owner", 0.4)):
            value = getattr(vessel, attribute, None)
            if not value:
                continue
            for entity in self.exact(value, {"company", "person"}):
                bonus = 0.05 if entity.country and entity.country == flag else 0
                add(self._match(entity, match_type, value, round(base + bonus, 2), "owner_match", similarity=1.0))
            for entity, score in self.fuzzy(value, {"company", "person"}, 0.9):
                add(self._match(entity, match_type, value, round(base - 0.1, 2), "owner_match", similarity=round(score, 3)))
        program = COMPREHENSIVE_PROGRAMS.get(flag or "")
        if program:
            add(
                Match(
                    entity=None,
                    match_type="flag_program",
                    matched_value=flag,
                    confidence=0.8,
                    breach_type="flag_violation",
                    authority="OFAC",
                    summary=f"Flag state {flag} falls under the comprehensive {program} sanctions programme",
                    programs=[program],
                )
            )
        matches.sort(key=lambda m: m.confidence, reverse=True)
        return matches

    @staticmethod
    def _name_confidence(entity: IndexedEntity, flag: str | None, vessel_imo: str | None, name: str, exact: bool) -> float:
        """Name matches are weak on their own: flags and (above all) IMO numbers decide.

        * listed flag agrees        exact 0.90 / fuzzy 0.70
        * listed flag unknown       exact 0.80 / fuzzy 0.50
        * listed flag differs       exact 0.55 / fuzzy 0.35  (review queue)
        * both IMOs known, differ   capped at 0.30  (a namesake, not the designated hull)
        * no IMO and a short name   capped at 0.50  (common names on small craft)
        """
        if entity.vessel_flag and entity.vessel_flag == flag:
            confidence = 0.9 if exact else 0.7
        elif not entity.vessel_flag:
            confidence = 0.8 if exact else 0.5
        else:
            confidence = 0.55 if exact else 0.35  # review queue: same name, different flag, no IMO to decide
        if entity.imo and vessel_imo and entity.imo != vessel_imo:
            confidence = min(confidence, 0.3)
        elif not vessel_imo and len(normalize_name(name)) <= 6:
            confidence = min(confidence, 0.5)
        return round(confidence, 2)

    @staticmethod
    def _match(entity: IndexedEntity, match_type: str, value: str, confidence: float, breach_type: str, similarity: float | None = None) -> Match:
        detail = f" (similarity {similarity:.2f})" if similarity is not None and similarity < 1 else ""
        label = ", ".join(entity.programs[:3]) or entity.entity_type
        return Match(
            entity=entity,
            match_type=match_type,
            matched_value=value,
            confidence=confidence,
            breach_type=breach_type,
            authority=entity.authority,
            summary=f"{MATCH_LABELS[match_type]} '{value}' matches {entity.authority} listing '{entity.name}' [{label}]{detail}",
            similarity=similarity,
            programs=entity.programs,
        )


# ---------------------------------------------------------------- list diffs
@dataclass
class ListChanges:
    authority: str
    new: list = field(default_factory=list)  # SanctionedEntityRecord
    relisted: list = field(default_factory=list)  # (existing_id, record)
    changed: list = field(default_factory=list)  # (existing_id, record, {field: (old, new)})
    unchanged: int = 0
    delisted: list = field(default_factory=list)  # existing rows (dicts) no longer present
    skipped_delisting: bool = False


def compare_sanctions_lists(existing: dict[str, dict], incoming: list, authority: str, min_fraction: float = 0.5) -> ListChanges:
    """Diff the incoming list against existing rows keyed by ``source_id``.

    ``existing`` values are dicts with ``id, source_id, name, programs, imo, is_active``.
    Delistings are skipped when the download looks truncated (fewer than
    ``min_fraction`` of the known active rows) so a bad fetch cannot mass-delist.
    """
    changes = ListChanges(authority=authority)
    seen: set[str] = set()
    for record in incoming:
        seen.add(record.source_id)
        current = existing.get(record.source_id)
        if current is None:
            changes.new.append(record)
            continue
        if not current["is_active"]:
            changes.relisted.append((current["id"], record))
            continue
        diff = {}
        if normalize_name(current["name"]) != normalize_name(record.name):
            diff["name"] = (current["name"], record.name)
        if set(current.get("programs") or []) != set(record.programs):
            diff["programs"] = (current.get("programs") or [], record.programs)
        if (current.get("imo") or None) != (record.imo or None):
            diff["imo"] = (current.get("imo"), record.imo)
        if diff:
            changes.changed.append((current["id"], record, diff))
        else:
            changes.unchanged += 1
    active_existing = [row for row in existing.values() if row["is_active"]]
    if active_existing and len(seen) < len(active_existing) * min_fraction:
        changes.skipped_delisting = True
    else:
        changes.delisted = [row for row in active_existing if row["source_id"] not in seen]
    return changes


IMO_RE = re.compile(r"^\d{7}$")


def looks_like_imo(value: str) -> bool:
    return bool(IMO_RE.match(value.strip()))
