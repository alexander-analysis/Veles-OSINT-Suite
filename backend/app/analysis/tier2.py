"""Tier 2 / 3 rules: aircraft registrations, breach relevance, narrative clustering, infrastructure risk."""

import hashlib
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime

from app.analysis.corporate import SECRECY_JURISDICTIONS, core_name, name_similarity
from app.integrations.sanctions_common import normalize_name

# Registration prefix -> ISO country (the ones that show up on sanctions lists first)
REGISTRATION_PREFIXES = {
    "EP": "IR", "EX": "KG", "UP": "KZ", "RA": "RU", "RF": "RU", "P": "KP", "YK": "SY", "YV": "VE", "CU": "CU", "EW": "BY", "UR": "UA", "T7": "SM", "9H": "MT",
    "VP-B": "BM", "VP-C": "KY", "M": "IM", "2": "GG", "N": "US", "G": "GB", "D": "DE", "F": "FR", "TC": "TR", "A6": "AE", "A7": "QA", "HZ": "SA", "4K": "AZ",
    "EK": "AM", "YI": "IQ", "OD": "LB", "SU": "EG", "5A": "LY", "ST": "SD", "B": "CN", "JY": "JO", "UN": "KZ", "4L": "GE", "ER": "MD", "LZ": "BG", "YR": "RO",
}
AIRCRAFT_REMARK_RE = {
    "model": re.compile(r"Aircraft Model ([^;]+)"),
    "operator": re.compile(r"Aircraft Operator ([^;]+)"),
    "msn": re.compile(r"Manufacturer's Serial Number \(MSN\) ([^;]+)"),
    "mode_s": re.compile(r"Aircraft Mode S Transponder Code ([0-9A-Fa-f]{6})"),
    "tail": re.compile(r"Aircraft Tail Number ([A-Z0-9-]+)"),
}


def registration_country(registration: str) -> str | None:
    """Country from the registration prefix ("EP-GOL" -> IR, "N123AB" -> US); hyphenated prefixes take precedence."""
    reg = registration.upper()
    for prefix in sorted(REGISTRATION_PREFIXES, key=len, reverse=True):
        if reg.startswith(prefix + "-"):
            return REGISTRATION_PREFIXES[prefix]
    for prefix in sorted(REGISTRATION_PREFIXES, key=len, reverse=True):
        if "-" not in prefix and reg.startswith(prefix) and (len(prefix) >= 2 or (prefix in ("N", "B") and len(reg) > 1 and reg[1].isdigit())):
            return REGISTRATION_PREFIXES[prefix]
    return None


def parse_aircraft_remarks(remarks: str | None) -> dict[str, str | None]:
    text = remarks or ""
    return {key: (pattern.search(text).group(1).strip() if pattern.search(text) else None) for key, pattern in AIRCRAFT_REMARK_RE.items()}


# --------------------------------------------------------------- breaches
CRITICAL_SECTORS = {
    "energy": ("energy", "oil", "gas", "petrol", "utilit", "power", "nuclear", "pipeline"),
    "maritime": ("maritime", "shipping", "port", "logistic", "vessel", "marine", "transport"),
    "finance": ("bank", "financ", "insur", "payment", "exchange", "crypto"),
    "government": ("government", "ministry", "public", "defense", "defence", "military", "municipal"),
    "telecom": ("telecom", "network", "internet"),
    "healthcare": ("health", "hospital", "pharma", "medical"),
}
WATCH_COUNTRIES = {"RU", "IR", "KP", "SY", "BY", "VE", "CU", "UA", "CN", "AE", "TR"}


@dataclass
class BreachRelevance:
    relevance: str
    score: float
    severity: str
    reasons: list[str] = field(default_factory=list)


def breach_relevance(victim_name: str, victim_domain: str | None, country: str | None, sector: str | None, matched_company: bool, matched_entity: bool, watch_keywords: list[str], records: int | None = None) -> BreachRelevance:
    reasons: list[str] = []
    score = 0.2
    relevance = "general"
    if matched_entity:
        relevance, score = "sanctioned_party", 0.95
        reasons.append("victim matches a sanctions listing")
    elif matched_company:
        relevance, score = "tracked_company", 0.85
        reasons.append("victim matches a tracked company")
    text = f"{victim_name} {victim_domain or ''} {sector or ''}".lower()
    for bucket, words in CRITICAL_SECTORS.items():
        if any(w in text for w in words):
            reasons.append(f"critical sector: {bucket}")
            if relevance == "general":
                relevance, score = "critical_sector", max(score, 0.6)
            else:
                score = min(1.0, score + 0.05)
            break
    for keyword in watch_keywords:
        if keyword and keyword.lower() in text:
            reasons.append(f"watch keyword: {keyword}")
            if relevance in ("general", "critical_sector"):
                relevance, score = "watch_keyword", max(score, 0.7)
    if country and country in WATCH_COUNTRIES:
        reasons.append(f"watch country: {country}")
        score = min(1.0, score + 0.1)
    if records and records >= 10_000_000:
        reasons.append(f"{records:,} records")
        score = min(1.0, score + 0.1)
    severity = "critical" if score >= 0.9 else "high" if score >= 0.7 else "medium" if score >= 0.5 else "low"
    return BreachRelevance(relevance, round(score, 2), severity, reasons)


class CompanyIndex:
    """Token index over tracked company names so a victim name is compared with a few dozen candidates, not 11,000."""

    def __init__(self, companies: list[tuple[int, str, str | None]]) -> None:
        self.names: dict[int, str] = {}
        self.countries: dict[int, str | None] = {}
        self.exact: dict[str, list[int]] = {}
        self.by_token: dict[str, list[int]] = {}
        for company_id, name, country in companies:
            core = core_name(name)
            if not core:
                continue
            self.names[company_id] = name
            self.countries[company_id] = country
            self.exact.setdefault(core, []).append(company_id)
            for token in core.split():
                if len(token) >= 4:
                    self.by_token.setdefault(token, []).append(company_id)

    def match(self, victim_name: str, victim_country: str | None = None, min_similarity: float = 0.92) -> tuple[int | None, str]:
        """(company id, strength) - strength is 'strong', 'weak' (single generic token, country unknown / different) or 'none'."""
        core = core_name(victim_name)
        tokens = core.split()
        if len(core) < 5 or not tokens:
            return None, "none"
        candidates: set[int] = set(self.exact.get(core, []))
        for token in tokens:
            if len(token) >= 4:
                candidates.update(self.by_token.get(token, [])[:300])
        best: tuple[int, float] | None = None
        for company_id in candidates:
            score = name_similarity(victim_name, self.names[company_id])
            if score >= min_similarity and (best is None or score > best[1]):
                best = (company_id, score)
        if best is None:
            return None, "none"
        if len(tokens) == 1:
            listed_country = self.countries.get(best[0])
            if not victim_country or not listed_country or victim_country != listed_country:
                return best[0], "weak"
        return best[0], "strong"


def company_match(victim_name: str, candidates: list[tuple[int, str]], min_similarity: float = 0.92) -> int | None:
    """Best tracked-company id for a victim name; single generic tokens are not accepted without a country check."""
    company_id, strength = CompanyIndex([(cid, name, None) for cid, name in candidates]).match(victim_name, None, min_similarity)
    return company_id if strength == "strong" else None


# ------------------------------------------------------------- narratives
STOP = set(
    "the a an and or of to in on for with by from at as is are was were be been has have had its their his her this that these those it not no will would could should "
    "may might can about over after before into than more most new says said say amid under against between during without within while "
    # too common across every state-media headline to separate one story from another
    "russia russian russians ukraine ukrainian ukrainians kiev kyiv moscow west western media state official officials minister ministry president attack attacks "
    "attacked report reports reported news week year years time first last country countries government military forces".split()
)


def topic_tokens(title: str) -> list[str]:
    tokens = [t for t in re.findall(r"[a-z][a-z-]{3,}", title.lower()) if t not in STOP]
    return tokens


@dataclass
class NarrativeCandidate:
    topic: str
    keywords: list[str]
    outlets: dict[str, int]
    items: list[dict]
    first_seen: datetime
    last_seen: datetime
    countries: list[str]

    @property
    def fingerprint(self) -> str:
        return hashlib.sha1(f"{'|'.join(sorted(self.keywords[:4]))}|{self.first_seen:%Y-%m-%d}".encode()).hexdigest()[:40]


def cluster_narratives(items: list[dict], min_items: int = 3, min_shared: int = 2) -> list[NarrativeCandidate]:
    """Group state-media headlines that share >= ``min_shared`` distinctive tokens.

    ``items``: {"title", "outlet", "time", "url", "countries"}.
    """
    tokenised = [(item, set(topic_tokens(item["title"]))) for item in items]
    freq: Counter[str] = Counter(t for _, toks in tokenised for t in toks)
    distinctive = {t for t, n in freq.items() if 2 <= n <= max(3, len(items) // 3)}
    groups: list[tuple[set[str], list[dict]]] = []
    for item, toks in tokenised:
        toks = toks & distinctive
        if len(toks) < min_shared:
            continue
        for keys, members in groups:
            if len(keys & toks) >= min_shared:
                members.append(item)
                keys |= toks
                break
        else:
            groups.append((set(toks), [item]))
    out: list[NarrativeCandidate] = []
    for keys, members in groups:
        if len(members) < min_items:
            continue
        outlets: Counter[str] = Counter(m["outlet"] for m in members)
        common = Counter(t for m in members for t in set(topic_tokens(m["title"])) & keys)
        keywords = [t for t, _ in common.most_common(6)]
        countries = sorted({c for m in members for c in (m.get("countries") or [])})
        times = [m["time"] for m in members]
        out.append(NarrativeCandidate(topic=" ".join(keywords[:4]), keywords=keywords, outlets=dict(outlets), items=members, first_seen=min(times), last_seen=max(times), countries=countries))
    out.sort(key=lambda n: (-len(n.outlets), -len(n.items)))
    return out


def narrative_assessment(candidate: NarrativeCandidate, western_matches: int) -> tuple[float, str, str, str]:
    outlets, items = len(candidate.outlets), len(candidate.items)
    score = min(1.0, 0.3 + 0.15 * outlets + 0.05 * items)
    if western_matches == 0:
        divergence = "state_only"
        score = min(1.0, score + 0.2)
    elif items >= 2 * western_matches:
        divergence = "amplified"
        score = min(1.0, score + 0.1)
    else:
        divergence = "mirrored"
        score = max(0.2, score - 0.2)
    severity = "high" if score >= 0.8 else "medium" if score >= 0.55 else "low"
    text = f"{items} items across {outlets} state outlet(s) ({', '.join(f'{k} {v}' for k, v in candidate.outlets.items())}); {western_matches} matching item(s) from official / non-state feeds - {divergence.replace('_', ' ')}."
    return round(score, 2), divergence, severity, text[:500]


# ------------------------------------------------------------------ infra
def infra_risk(registrar: str | None, hosting_country: str | None, is_live: bool | None, certificate_count: int, nameservers: list[str], entity_linked: bool) -> tuple[float, list[str]]:
    findings: list[str] = []
    score = 0.3 if entity_linked else 0.1
    if is_live:
        findings.append("domain resolves (live infrastructure of a listed party)" if entity_linked else "domain resolves")
        score += 0.25
    elif is_live is False:
        findings.append("does not resolve")
    if hosting_country in SECRECY_JURISDICTIONS or hosting_country in ("RU", "IR", "CN", "HK"):
        findings.append(f"hosted in {hosting_country}")
        score += 0.15
    if hosting_country in ("US", "DE", "NL", "GB", "FR") and entity_linked:
        findings.append(f"hosted in {hosting_country} - provider exposure")
        score += 0.2
    if certificate_count >= 20:
        findings.append(f"{certificate_count} certificates in CT logs - active subdomain estate")
        score += 0.1
    if any("cloudflare" in ns for ns in nameservers):
        findings.append("behind Cloudflare")
    if registrar:
        findings.append(f"registrar {registrar}")
    return round(min(score, 1.0), 2), findings


def normalized(value: str | None) -> str:
    return normalize_name(value)
