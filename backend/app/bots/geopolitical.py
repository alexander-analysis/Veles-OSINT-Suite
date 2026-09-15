"""Geopolitical event monitor (ecosystem bot 4).

Sources (all keyless): GDELT 2.0 event exports every 15 minutes, GDELT DOC
topic searches (maritime incidents, port closures, sanctions, infrastructure,
trade), and official feeds (gov.uk FCDO, UN press, OFAC recent actions).
Events are classified, scored and then correlated against the market,
maritime and sanctions signals the other bots produce.
"""

import asyncio
from collections import Counter
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.analysis.geopolitical import ASSET_SECTORS, DEFAULT_WATCHLIST, EventDraft, classify_text_or_none, draft_from_article, draft_from_gdelt, relevance, time_score
from app.database import SessionLocal
from app.integrations.feeds import FeedItem, fetch_feed, fetch_ofac_recent_actions
from app.integrations.gdelt import GdeltClient
from app.models.audit import AuditLog
from app.models.geopolitical import EventCorrelation, GeopoliticalEvent, NewsSource
from app.models.maritime import EvasionEvent, SanctionsBreach, TransshipmentEvent, Vessel
from app.models.market import MarketAlert
from app.models.sanctions import SanctionsEntity, SanctionsUpdate
from app.utils import config_store
from app.utils.logger import logger
from app.utils.time import utcnow

log = logger.bind(component="geopolitical")

SEVERITY_RANK = {"low": 0, "medium": 1, "high": 2, "critical": 3}
DEFAULT_TOPICS = [
    {"query": "(tanker OR vessel OR ship) (seized OR detained OR boarded OR attacked OR hijacked)", "event_type": "maritime_incident"},
    {"query": "(port OR strait OR canal) (closed OR closure OR blockade OR suspended)", "event_type": "port_closure"},
    {"query": "(sanctions OR OFAC) (shipping OR tanker OR vessel OR crypto OR bank)", "event_type": "sanctions"},
    {"query": '(pipeline OR refinery OR "LNG terminal" OR "oil depot") (attack OR explosion OR fire OR halted OR drone)', "event_type": "infrastructure"},
    {"query": '("export ban" OR tariff OR embargo) (oil OR gas OR grain OR metals OR fertilizer)', "event_type": "trade"},
]
DEFAULT_FEEDS = [
    {"name": "gov_uk_fcdo", "url": "https://www.gov.uk/government/organisations/foreign-commonwealth-development-office.atom", "type": "government", "reliability": 0.9},
    {"name": "un_press", "url": "https://press.un.org/en/rss.xml", "type": "government", "reliability": 0.9},
    {"name": "ofac_recent_actions", "url": "https://ofac.treasury.gov/recent-actions", "type": "government", "reliability": 0.95},
    # State media: low reliability, kept only when the headline matches a monitored topic (also feeds the disinformation monitor)
    {"name": "rt", "url": "https://www.rt.com/rss/news/", "type": "state_media", "reliability": 0.3, "country": "RU"},
    {"name": "tass", "url": "https://tass.com/rss/v2.xml", "type": "state_media", "reliability": 0.35, "country": "RU"},
    {"name": "global_times", "url": "https://www.globaltimes.cn/rss/outbrain.xml", "type": "state_media", "reliability": 0.35, "country": "CN"},
]


def _config() -> dict[str, Any]:
    return config_store.get_config().get("geopolitical", {})


def _parse_seendate(value: str | None) -> datetime | None:
    # GDELT DOC "20260915T091500Z"
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y%m%dT%H%M%SZ")
    except ValueError:
        return None


class GeopoliticalBot:
    def __init__(self) -> None:
        self.gdelt = GdeltClient()
        self.last_run: dict[str, datetime] = {}
        self.last_result: dict[str, Any] = {}
        self._url_cache: dict[str, datetime] = {}
        self._url_cache_loaded = False

    # -------------------------------------------------------------- status
    def status(self) -> dict[str, Any]:
        return {
            "last_run": {k: v for k, v in self.last_run.items()},
            "last_result": self.last_result,
            "last_gdelt_export": self.gdelt.last_export_url.rsplit("/", 1)[-1] if self.gdelt.last_export_url else None,
        }

    # ------------------------------------------------------------- storage
    def _load_url_cache(self, db: Session) -> None:
        since = utcnow() - timedelta(days=3)
        rows = db.execute(select(GeopoliticalEvent.source_urls, GeopoliticalEvent.detected_date).where(GeopoliticalEvent.detected_date >= since)).all()
        for urls, seen in rows:
            for url in urls or []:
                self._url_cache[url] = seen
        self._url_cache_loaded = True

    def _prune_url_cache(self) -> None:
        cutoff = utcnow() - timedelta(days=3)
        for url in [u for u, seen in self._url_cache.items() if seen < cutoff]:
            del self._url_cache[url]

    def _store(self, drafts: list[EventDraft]) -> dict[str, Any]:
        """Insert new events (deduplicated by provider id and by article URL); returns counts + new critical events."""
        if not drafts:
            return {"inserted": 0, "duplicates": 0}
        with SessionLocal() as db:
            if not self._url_cache_loaded:
                self._load_url_cache(db)
            self._prune_url_cache()
            existing_ids = {
                (s, i)
                for s, i in db.execute(
                    select(GeopoliticalEvent.source, GeopoliticalEvent.source_id).where(GeopoliticalEvent.source_id.in_([d.source_id for d in drafts]))
                ).all()
            }
            inserted, duplicates = 0, 0
            now = utcnow()
            critical: list[dict[str, Any]] = []
            batch_urls: set[str] = set()
            for draft in sorted(drafts, key=lambda d: -(d.mentions or 0)):
                url = draft.source_urls[0] if draft.source_urls else None
                if (draft.source, draft.source_id) in existing_ids or (url and (url in self._url_cache or url in batch_urls)):
                    duplicates += 1
                    continue
                event = GeopoliticalEvent(
                    event_type=draft.event_type,
                    title=draft.title,
                    description=draft.description,
                    country_primary=draft.country_primary,
                    country_secondary=draft.country_secondary,
                    region=(draft.region or "")[:100] or None,
                    coordinates_lat=draft.lat,
                    coordinates_lon=draft.lon,
                    event_date=draft.event_date,
                    detected_date=now,
                    severity=draft.severity,
                    source=draft.source,
                    source_id=draft.source_id,
                    source_urls=draft.source_urls,
                    verification_status="confirmed" if draft.source in ("gov_uk_fcdo", "un_press", "ofac_recent_actions") else "unconfirmed",
                    confidence_score=draft.confidence,
                    keywords=draft.keywords,
                    affected_sectors=draft.sectors,
                    affected_countries=draft.affected_countries,
                    goldstein_scale=draft.goldstein,
                    mentions=draft.mentions,
                    market_impact=draft.market_impact,
                    supply_chain_impact=draft.supply_chain_impact,
                )
                db.add(event)
                inserted += 1
                existing_ids.add((draft.source, draft.source_id))
                if url:
                    batch_urls.add(url)
                    self._url_cache[url] = now
                if draft.severity == "critical":
                    critical.append({"title": draft.title, "country": draft.country_primary, "type": draft.event_type, "url": url})
            db.commit()
        if inserted:
            self._publish(inserted, critical)
        return {"inserted": inserted, "duplicates": duplicates}

    @staticmethod
    def _publish(inserted: int, critical: list[dict[str, Any]]) -> None:
        try:
            from app.api.stream import manager

            manager.publish("geopolitical_events", {"inserted": inserted, "critical": critical[:5]})
        except Exception:  # noqa: BLE001 - the websocket fan-out is best effort
            pass
        cfg = _config()
        min_sev = cfg.get("alert_min_severity", "critical")
        if SEVERITY_RANK.get(min_sev, 3) <= SEVERITY_RANK["critical"]:
            from app import notifications

            for item in critical[:3]:
                notifications.send_alert("geopolitical", item["title"], f"{item['type']} in {item['country'] or '?'}: {item['url'] or ''}", severity="critical", data=item)

    # ----------------------------------------------------------- GDELT jobs
    async def fetch_gdelt_events(self) -> dict[str, Any]:
        cfg = _config()
        if not cfg.get("enabled", True):
            return {"skipped": "disabled"}
        events = await self.gdelt.fetch_latest_events()
        min_mentions = int(cfg.get("gdelt_min_mentions", 8))
        watchlist = set(cfg.get("watchlist_countries") or DEFAULT_WATCHLIST)
        drafts = [d for d in (draft_from_gdelt(e, min_mentions, watchlist) for e in events) if d]
        result = await asyncio.to_thread(self._store, drafts)
        result["rows"] = len(events)
        result["candidates"] = len(drafts)
        self.last_run["gdelt_events"] = utcnow()
        self.last_result["gdelt_events"] = result
        log.info("gdelt events: {}", result)
        return result

    async def fetch_topic_articles(self) -> dict[str, Any]:
        cfg = _config()
        if not cfg.get("enabled", True):
            return {"skipped": "disabled"}
        topics = cfg.get("doc_topics") or DEFAULT_TOPICS
        timespan = str(cfg.get("doc_timespan", "2h"))
        self.gdelt.min_interval = float(cfg.get("doc_min_interval_seconds", 15))
        drafts: list[EventDraft] = []
        per_topic: dict[str, int | str] = {}
        for topic in topics:
            try:
                articles = await self.gdelt.search_articles(topic["query"], timespan=timespan, max_records=int(cfg.get("doc_max_records", 40)))
            except Exception as exc:  # noqa: BLE001 - keep going with the next topic
                log.warning("doc query failed ({}): {}", topic.get("event_type"), exc)
                continue
            if self.gdelt.rate_limited:
                per_topic[topic.get("event_type", "?")] = "rate_limited"
                break  # the API asked us to back off - retry next run instead of hammering it
            per_topic[topic.get("event_type", "?")] = len(articles)
            for article in articles:
                title, url = (article.get("title") or "").strip(), (article.get("url") or "").strip()
                if not title or not url or article.get("language", "English") != "English":
                    continue
                drafts.append(
                    draft_from_article(title, url, _parse_seendate(article.get("seendate")) or utcnow(), "gdelt_doc", topic.get("event_type"), article.get("domain"), 0.5)
                )
        result = await asyncio.to_thread(self._store, drafts)
        result["articles"] = per_topic
        self.last_run["gdelt_doc"] = utcnow()
        self.last_result["gdelt_doc"] = result
        log.info("gdelt doc: {}", result)
        return result

    # --------------------------------------------------------- official feeds
    async def fetch_official_feeds(self) -> dict[str, Any]:
        cfg = _config()
        if not cfg.get("enabled", True):
            return {"skipped": "disabled"}
        feeds = cfg.get("official_feeds") or DEFAULT_FEEDS
        drafts: list[EventDraft] = []
        outcome: dict[str, Any] = {}
        for feed in feeds:
            if not feed.get("enabled", True):
                continue
            name = feed["name"]
            started = utcnow()
            try:
                items = await fetch_ofac_recent_actions() if name == "ofac_recent_actions" else await fetch_feed(feed["url"], name)
                status = f"ok: {len(items)} items"
            except Exception as exc:  # noqa: BLE001
                items, status = [], f"error: {exc}"[:200]
                log.warning("feed {} failed: {}", name, exc)
            outcome[name] = status
            await asyncio.to_thread(self._touch_source, feed, status, len(items), int((utcnow() - started).total_seconds()))
            for item in items:
                draft = self._draft_from_feed(item, feed)
                if draft is not None:
                    drafts.append(draft)
        result = await asyncio.to_thread(self._store, drafts)
        result["feeds"] = outcome
        self.last_run["official_feeds"] = utcnow()
        self.last_result["official_feeds"] = result
        log.info("official feeds: {}", result)
        return result

    @staticmethod
    def _draft_from_feed(item: FeedItem, feed: dict[str, Any]) -> EventDraft | None:
        topic_type = "sanctions" if feed["name"] == "ofac_recent_actions" else None
        if feed.get("type") in ("state_media", "news") and topic_type is None:
            # Non-official outlets: keep only headlines that hit a monitored topic
            topic_type = classify_text_or_none(item.title)
            if topic_type is None:
                return None
        draft = draft_from_article(item.title, item.link, item.published or utcnow(), feed["name"], topic_type, feed.get("name"), float(feed.get("reliability", 0.8)))
        draft.source_id = (item.guid or item.link)[:120]
        if feed.get("country") and feed["country"] not in draft.affected_countries:
            draft.affected_countries = [*draft.affected_countries, feed["country"]]
        if feed.get("type") == "state_media":
            draft.keywords = [*draft.keywords, "state_media"]
        if item.summary and item.summary != item.title:
            draft.description = f"{item.summary[:600]} Source: {item.link}"
        return draft

    @staticmethod
    def _touch_source(feed: dict[str, Any], status: str, items: int, latency: int) -> None:
        with SessionLocal() as db:
            row = db.execute(select(NewsSource).where(NewsSource.source_name == feed["name"])).scalar_one_or_none()
            if row is None:
                row = NewsSource(source_name=feed["name"], source_url=feed.get("url"), source_type=feed.get("type", "government"), categories=feed.get("categories") or ["official"], reliability_score=feed.get("reliability"))
                db.add(row)
            row.last_fetch = utcnow()
            row.last_status = status
            row.items_total = (row.items_total or 0) + items
            row.latency_seconds = latency
            db.commit()

    # ------------------------------------------------------------ correlation
    async def correlate(self) -> dict[str, Any]:
        cfg = _config()
        if not cfg.get("enabled", True):
            return {"skipped": "disabled"}
        result = await asyncio.to_thread(self._correlate, float(cfg.get("correlation_window_hours", 24)), float(cfg.get("min_correlation_score", 0.55)), str(cfg.get("correlation_min_severity", "medium")))
        self.last_run["correlate"] = utcnow()
        self.last_result["correlate"] = result
        log.info("correlation: {}", result)
        return result

    @staticmethod
    def _signals(db: Session, start: datetime, end: datetime) -> list[dict[str, Any]]:
        signals: list[dict[str, Any]] = []
        for alert in db.execute(select(MarketAlert).where(MarketAlert.timestamp.between(start, end))).scalars():
            signals.append({"kind": "market_alert", "id": alert.id, "time": alert.timestamp, "sector": ASSET_SECTORS.get(alert.asset, "finance"), "countries": [],
                            "summary": alert.summary or f"{alert.asset} {alert.alert_type} ({alert.severity})", "severity": alert.severity})
        for breach in db.execute(select(SanctionsBreach).where(SanctionsBreach.timestamp.between(start, end))).scalars():
            signals.append({"kind": "sanctions_breach", "id": breach.id, "time": breach.timestamp, "sector": "shipping", "countries": [c for c in (breach.flag,) if c],
                            "summary": f"{breach.sanctioning_authority} match: {breach.vessel_name} -> {breach.sanctioned_entity_name}", "severity": breach.severity})
        flags = dict(db.execute(select(Vessel.id, Vessel.flag_state).where(Vessel.id.in_(
            select(EvasionEvent.vessel_id).where(EvasionEvent.timestamp.between(start, end))))).all())
        for ev in db.execute(select(EvasionEvent).where(EvasionEvent.timestamp.between(start, end))).scalars():
            signals.append({"kind": "evasion_event", "id": ev.id, "time": ev.timestamp, "sector": "shipping", "countries": [c for c in (flags.get(ev.vessel_id),) if c],
                            "summary": ev.summary or f"{ev.event_type} {ev.mmsi}", "severity": ev.severity})
        for sts in db.execute(select(TransshipmentEvent).where(TransshipmentEvent.timestamp.between(start, end))).scalars():
            signals.append({"kind": "transshipment", "id": sts.id, "time": sts.timestamp, "sector": "shipping", "countries": [],
                            "summary": f"STS candidate {sts.vessel_a_mmsi}/{sts.vessel_b_mmsi} ({(sts.confidence_score or 0):.2f})", "severity": "medium"})
        rows = db.execute(
            select(SanctionsUpdate, SanctionsEntity.country_linked).outerjoin(SanctionsEntity, SanctionsEntity.id == SanctionsUpdate.entity_id)
            .where(SanctionsUpdate.timestamp.between(start, end), SanctionsUpdate.update_type.in_(["new_designation", "relisted", "delisting"]))
        ).all()
        for upd, country in rows:
            signals.append({"kind": "sanctions_update", "id": upd.id, "time": upd.timestamp, "sector": "finance", "countries": [c for c in (country,) if c],
                            "summary": f"{upd.authority} {upd.update_type}: {upd.entity_name}", "severity": "medium"})
        return signals

    @staticmethod
    def _correlate(window_hours: float, min_score: float, min_severity: str) -> dict[str, Any]:
        now = utcnow()
        with SessionLocal() as db:
            events = db.execute(
                select(GeopoliticalEvent)
                .where(GeopoliticalEvent.event_date >= now - timedelta(hours=window_hours * 2))
                .order_by(GeopoliticalEvent.event_date.desc())
                .limit(300)
            ).scalars().all()
            events = [e for e in events if SEVERITY_RANK.get(e.severity, 0) >= SEVERITY_RANK.get(min_severity, 1)]
            if not events:
                return {"events": 0, "signals": 0, "correlations": 0}
            start = min(e.event_date for e in events) - timedelta(hours=window_hours)
            end = max(e.event_date for e in events) + timedelta(hours=window_hours)
            signals = GeopoliticalBot._signals(db, start, end)
            if not signals:
                return {"events": len(events), "signals": 0, "correlations": 0}
            existing = {
                (c.geopolitical_event_id, c.alert_type, c.alert_id)
                for c in db.execute(select(EventCorrelation).where(EventCorrelation.geopolitical_event_id.in_([e.id for e in events]))).scalars()
            }
            created = 0
            by_kind: Counter[str] = Counter()
            for event in events:
                sectors = list(event.affected_sectors or [])
                countries = list(event.affected_countries or [])
                for signal in signals:
                    key = (event.id, signal["kind"], signal["id"])
                    if key in existing:
                        continue
                    t_score = time_score(event.event_date, signal["time"], window_hours)
                    if t_score <= 0:
                        continue
                    r_score, shared = relevance(sectors, countries, event.event_type, signal)
                    if r_score <= 0:
                        continue
                    score = round(0.7 * r_score + 0.3 * t_score, 3)
                    if score < min_score:
                        continue
                    delta = int((signal["time"] - event.event_date).total_seconds() // 60)
                    direction = "simultaneous" if abs(delta) <= 15 else ("after" if delta > 0 else "before")
                    ctype = "geographic" if any(k.startswith("country:") for k in shared) else ("topical" if shared else "temporal")
                    db.add(
                        EventCorrelation(
                            geopolitical_event_id=event.id,
                            event_type=event.event_type,
                            event_date=event.event_date,
                            alert_type=signal["kind"],
                            alert_id=signal["id"],
                            alert_timestamp=signal["time"],
                            alert_summary=signal["summary"][:300],
                            time_delta_minutes=delta,
                            time_delta_direction=direction,
                            correlation_score=score,
                            correlation_type=ctype,
                            intelligence_analysis=f"{event.title[:120]} <-> {signal['summary'][:120]}: {ctype} link ({', '.join(shared) or 'time only'}), {abs(delta)} min {direction}.",
                        )
                    )
                    existing.add(key)
                    created += 1
                    by_kind[signal["kind"]] += 1
                    if signal["kind"] == "market_alert":
                        event.correlated_with_market = True
                    elif signal["kind"] in ("sanctions_breach", "evasion_event", "transshipment"):
                        event.correlated_with_maritime = True
                    if signal["kind"] in ("sanctions_update", "sanctions_breach"):
                        event.correlated_with_sanctions = True
            if created:
                db.add(AuditLog(action_type="geopolitical_correlation", user_id="system", rationale=f"{created} event/signal correlation(s) recorded",
                                supporting_data=dict(by_kind), source_systems=["bots.geopolitical"], created_by="system"))
            db.commit()
        return {"events": len(events), "signals": len(signals), "correlations": created, "by_kind": dict(by_kind)}

    # -------------------------------------------------------------- retention
    async def cleanup_old_data(self) -> dict[str, int]:
        days = int(config_store.get_config().get("retention", {}).get("geopolitical_events_days", 90))
        cutoff = utcnow() - timedelta(days=days)

        def _purge() -> dict[str, int]:
            with SessionLocal() as db:
                old_ids = [i for (i,) in db.execute(select(GeopoliticalEvent.id).where(GeopoliticalEvent.event_date < cutoff)).all()]
                if not old_ids:
                    return {"events": 0, "correlations": 0}
                corr = db.execute(delete(EventCorrelation).where(EventCorrelation.geopolitical_event_id.in_(old_ids))).rowcount
                ev = db.execute(delete(GeopoliticalEvent).where(GeopoliticalEvent.id.in_(old_ids))).rowcount
                db.commit()
                return {"events": ev, "correlations": corr}

        result = await asyncio.to_thread(_purge)
        log.info("retention purge: {}", result)
        return result

    # ---------------------------------------------------------------- summary
    @staticmethod
    def summary(db: Session, hours: int = 24) -> dict[str, Any]:
        since = utcnow() - timedelta(hours=hours)
        base = select(GeopoliticalEvent).where(GeopoliticalEvent.event_date >= since)
        total = db.execute(select(func.count()).select_from(base.subquery())).scalar() or 0
        by_type = dict(db.execute(select(GeopoliticalEvent.event_type, func.count()).where(GeopoliticalEvent.event_date >= since).group_by(GeopoliticalEvent.event_type)).all())
        by_severity = dict(db.execute(select(GeopoliticalEvent.severity, func.count()).where(GeopoliticalEvent.event_date >= since).group_by(GeopoliticalEvent.severity)).all())
        top_countries = db.execute(
            select(GeopoliticalEvent.country_primary, func.count().label("n"))
            .where(GeopoliticalEvent.event_date >= since, GeopoliticalEvent.country_primary.is_not(None))
            .group_by(GeopoliticalEvent.country_primary).order_by(func.count().desc()).limit(10)
        ).all()
        correlated = db.execute(select(func.count(EventCorrelation.id)).where(EventCorrelation.detected_at >= since)).scalar() or 0
        return {
            "hours": hours,
            "total": total,
            "by_type": by_type,
            "by_severity": by_severity,
            "top_countries": [{"country": c, "events": n} for c, n in top_countries],
            "correlations": correlated,
        }


geopolitical_bot = GeopoliticalBot()
