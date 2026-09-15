"""Cross-bot correlation rules (ecosystem Part 4).

Every bot output is reduced to a ``Signal`` carrying typed keys (vessels,
entities, countries, assets, sectors, facilities).  Two signals from different
domains correlate when they share keys inside the time window; clusters of
correlated signals spanning three or more domains become composite alerts.
"""

import hashlib
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime

SEVERITY_RANK = {"low": 0, "medium": 1, "high": 2, "critical": 3}
RANK_SEVERITY = {v: k for k, v in SEVERITY_RANK.items()}

# how much a shared key of each kind says about a real link
KEY_WEIGHTS = {"vessel": 0.9, "entity": 0.8, "wallet": 0.8, "company": 0.75, "facility": 0.6, "country": 0.35, "asset": 0.35, "sector": 0.25, "theme": 0.3}
DOMAIN_OF_TYPE = {
    "market_alert": "market", "coordination_event": "market", "liquidation_cascade": "market",
    "sanctions_breach": "maritime", "evasion_event": "maritime", "transshipment": "maritime", "port_call": "maritime",
    "sanctions_update": "sanctions",
    "geopolitical_event": "geopolitical",
    "blockchain_tx": "blockchain",
    "corporate_exposure": "corporate",
    "dark_oil": "energy", "oil_shipment": "energy",
}


@dataclass
class Signal:
    type: str
    id: int
    time: datetime
    summary: str
    severity: str = "medium"
    keys: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))

    @property
    def domain(self) -> str:
        return DOMAIN_OF_TYPE.get(self.type, self.type)

    @property
    def ref(self) -> str:
        return f"{self.type}:{self.id}"

    def add(self, kind: str, *values: str | None) -> None:
        for value in values:
            if value:
                self.keys.setdefault(kind, set()).add(str(value).strip().upper() if kind in ("entity", "company", "country", "asset") else str(value).strip())


@dataclass
class Pair:
    a: Signal
    b: Signal
    score: float
    shared: list[str]
    correlation_type: str
    delta_minutes: int


def shared_keys(a: Signal, b: Signal) -> tuple[float, list[str]]:
    score, shared = 0.0, []
    for kind, weight in KEY_WEIGHTS.items():
        common = a.keys.get(kind, set()) & b.keys.get(kind, set())
        if common:
            score += weight * (1 if kind in ("vessel", "entity", "wallet", "company", "facility") else min(1.0, 0.6 + 0.2 * len(common)))
            shared.extend(f"{kind}:{c}" for c in sorted(common)[:5])
    return min(score, 1.0), shared


def time_factor(a: datetime, b: datetime, window_hours: float) -> float:
    delta = abs((a - b).total_seconds()) / 3600
    if delta > window_hours:
        return 0.0
    return 1.0 - 0.5 * (delta / window_hours)


STRONG_KINDS = ("vessel", "entity", "wallet", "company", "facility")
WEAK_GROUP_LIMIT = {"country": 40, "asset": 60, "sector": 25, "theme": 25}


def correlate(signals: list[Signal], window_hours: float = 48, min_score: float = 0.45, max_pairs: int = 5000, weak_window_hours: float = 6.0) -> list[Pair]:
    """All cross-domain pairs sharing a key inside the window, best first.

    Strong keys (a specific vessel, listed party, wallet, company or facility) link across the full
    window.  Weak keys (country, asset, sector, theme) only link inside ``weak_window_hours`` and only
    when the key is shared by a small group - "country:RU" on five hundred signals is not a lead.
    """
    by_key: dict[tuple[str, str], list[Signal]] = defaultdict(list)
    for signal in signals:
        for kind, values in signal.keys.items():
            for value in values:
                by_key[(kind, value)].append(signal)
    seen: set[tuple[str, str]] = set()
    pairs: list[Pair] = []
    for (kind, _), members in by_key.items():
        if kind in WEAK_GROUP_LIMIT and len(members) > WEAK_GROUP_LIMIT[kind]:
            continue
        if len(members) > 400:
            continue
        for i, a in enumerate(members):
            for b in members[i + 1:]:
                if a.domain == b.domain:
                    continue
                key = (a.ref, b.ref) if a.ref < b.ref else (b.ref, a.ref)
                if key in seen:
                    continue
                seen.add(key)
                raw, shared = shared_keys(a, b)
                strong = any(k.split(":")[0] in STRONG_KINDS for k in shared)
                factor = time_factor(a.time, b.time, window_hours if strong else min(window_hours, weak_window_hours))
                if factor == 0:
                    continue
                score = round(raw * factor, 3)
                if score < min_score:
                    continue
                strongest = shared[0].split(":")[0] if shared else "time"
                ctype = {"vessel": "entity", "entity": "entity", "wallet": "entity", "company": "entity", "facility": "geographic", "country": "geographic", "asset": "topical", "sector": "topical", "theme": "topical"}.get(strongest, "temporal")
                delta = int((b.time - a.time).total_seconds() // 60)
                pairs.append(Pair(a, b, score, shared, ctype, delta))
                if len(pairs) >= max_pairs:
                    break
    pairs.sort(key=lambda p: -p.score)
    return pairs


@dataclass
class Cluster:
    signals: list[Signal]
    pairs: list[Pair]
    anchor: str
    domains: list[str]
    confidence: float
    severity: str
    window_start: datetime
    window_end: datetime
    shared: list[str]

    @property
    def fingerprint(self) -> str:
        return hashlib.sha1(f"{self.anchor}|{self.window_start:%Y-%m-%d}".encode()).hexdigest()[:40]


def clusters(pairs: list[Pair], min_domains: int = 3, max_signals: int = 25) -> list[Cluster]:
    """Union-find over pairs that share a strong key; keep clusters spanning >= ``min_domains`` bot domains.

    Weak-key pairs (country / asset / sector) are kept as correlations but never glue clusters together,
    otherwise every Russian signal of the day collapses into one alert.
    """
    parent: dict[str, str] = {}
    signals: dict[str, Signal] = {}
    pairs = [p for p in pairs if any(k.split(":")[0] in STRONG_KINDS for k in p.shared)]

    def find(x: str) -> str:
        while parent.setdefault(x, x) != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for pair in pairs:
        signals[pair.a.ref] = pair.a
        signals[pair.b.ref] = pair.b
        ra, rb = find(pair.a.ref), find(pair.b.ref)
        if ra != rb:
            parent[ra] = rb
    groups: dict[str, list[Pair]] = defaultdict(list)
    for pair in pairs:
        groups[find(pair.a.ref)].append(pair)
    out: list[Cluster] = []
    for root, group_pairs in groups.items():
        members = {p.a.ref: p.a for p in group_pairs} | {p.b.ref: p.b for p in group_pairs}
        domains = sorted({s.domain for s in members.values()})
        if len(domains) < min_domains:
            continue
        key_counts: Counter[str] = Counter(k for p in group_pairs for k in p.shared if not k.startswith(("sector:", "theme:")))
        if not key_counts:
            key_counts = Counter(k for p in group_pairs for k in p.shared)
        anchor = key_counts.most_common(1)[0][0] if key_counts else root
        ordered = sorted(members.values(), key=lambda s: (-SEVERITY_RANK.get(s.severity, 0), s.time))[:max_signals]
        confidence = round(min(1.0, sum(p.score for p in group_pairs) / len(group_pairs) * (1 + 0.1 * (len(domains) - 3))), 3)
        severity = RANK_SEVERITY[max(SEVERITY_RANK.get(s.severity, 0) for s in ordered)]
        if len(domains) >= 4 and severity != "critical":
            severity = RANK_SEVERITY[min(3, SEVERITY_RANK[severity] + 1)]
        times = [s.time for s in members.values()]
        out.append(Cluster(ordered, group_pairs, anchor, domains, confidence, severity, min(times), max(times), [k for k, _ in key_counts.most_common(8)]))
    out.sort(key=lambda c: (-SEVERITY_RANK.get(c.severity, 0), -c.confidence))
    return out


def narrative(cluster: Cluster) -> str:
    """Analyst-readable summary: one clause per domain, strongest signals first."""
    by_domain: dict[str, list[Signal]] = defaultdict(list)
    for signal in cluster.signals:
        by_domain[signal.domain].append(signal)
    parts = []
    for domain in cluster.domains:
        items = by_domain.get(domain, [])
        if not items:
            continue
        head = items[0].summary
        more = f" (+{len(items) - 1} more)" if len(items) > 1 else ""
        parts.append(f"{domain.upper()}: {head}{more}")
    anchor_kind, _, anchor_value = cluster.anchor.partition(":")
    lead = f"Multi-domain pattern around {anchor_kind} {anchor_value}: {len(cluster.signals)} signals across {len(cluster.domains)} domains between {cluster.window_start:%d %b %H:%M} and {cluster.window_end:%d %b %H:%M} UTC."
    return (lead + " " + " | ".join(parts))[:4000]


def title_for(cluster: Cluster) -> str:
    kind, _, value = cluster.anchor.partition(":")
    label = {"vessel": "Vessel", "entity": "Listed party", "wallet": "Wallet", "company": "Company", "facility": "Facility", "country": "Country", "asset": "Asset", "sector": "Sector", "theme": "Theme"}.get(kind, kind)
    return f"{label} {value}: {' + '.join(cluster.domains)}"[:300]
