"""Legal / regulatory monitor (ecosystem tier 3).

* OFAC civil-penalty page and DOJ press releases (sanctions / export-control
  keywords) are polled directly.
* CourtListener is searched for the names of the most relevant listed parties in
  rotation (major shipping / energy / financial designations first) - dockets that
  name a listed party are stored with the matched listing.
"""

import asyncio
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.analysis.corporate import core_name, latin_enough
from app.database import SessionLocal
from app.integrations import legal
from app.models.sanctions import SanctionsEntity
from app.models.tier2 import LegalEvent
from app.utils import config_store
from app.utils.logger import logger
from app.utils.time import utcnow

log = logger.bind(component="legal")

PRIORITY_PROGRAMS = ("RUSSIA", "IRAN", "DPRK", "NORTH KOREA", "SYRIA", "VENEZUELA", "CYBER", "SDGT", "BELARUS")


def _config() -> dict[str, Any]:
    return config_store.get_config().get("legal", {})


class LegalBot:
    def __init__(self) -> None:
        self.last_run: dict[str, datetime] = {}
        self.last_result: dict[str, Any] = {}
        self._cursor = 0

    def status(self) -> dict[str, Any]:
        return {"last_run": dict(self.last_run), "last_result": self.last_result, "cursor": self._cursor}

    async def fetch_official(self) -> dict[str, Any]:
        cfg = _config()
        if not cfg.get("enabled", True):
            return {"skipped": "disabled"}
        records: list[legal.LegalRecord] = []
        outcome: dict[str, Any] = {}
        for name, fetcher in (("ofac_enforcement", legal.fetch_ofac_penalties), ("doj", legal.fetch_doj)):
            try:
                rows = await fetcher()
                records.extend(rows)
                outcome[name] = len(rows)
            except Exception as exc:  # noqa: BLE001
                outcome[name] = f"error: {exc}"[:120]
                log.warning("{} failed: {}", name, exc)
        stored = await asyncio.to_thread(self._store, records, None)
        result = {**outcome, **stored}
        self.last_run["official"] = utcnow()
        self.last_result["official"] = result
        log.info("official sources: {}", result)
        return result

    async def search_dockets(self) -> dict[str, Any]:
        cfg = _config()
        if not cfg.get("enabled", True) or not cfg.get("courtlistener_enabled", True):
            return {"skipped": "disabled"}
        batch = int(cfg.get("courtlistener_batch", 8))
        names = await asyncio.to_thread(self._query_names)
        if not names:
            return {"queries": 0}
        start = self._cursor % len(names)
        selected = [names[(start + i) % len(names)] for i in range(min(batch, len(names)))]
        self._cursor = (start + batch) % len(names)
        result = {"queries": 0, "hits": 0, "errors": 0}
        for entity_id, name in selected:
            query = core_name(name).title() if len(core_name(name)) >= 4 else name
            try:
                rows = await legal.search_courtlistener(query)
                result["queries"] += 1
                stored = await asyncio.to_thread(self._store, rows, entity_id)
                result["hits"] += stored["inserted"]
            except Exception as exc:  # noqa: BLE001
                result["errors"] += 1
                log.debug("courtlistener {} failed: {}", query, exc)
        self.last_run["dockets"] = utcnow()
        self.last_result["dockets"] = result
        log.info("dockets: {}", result)
        return result

    @staticmethod
    def _query_names() -> list[tuple[int, str]]:
        """Listed companies in the priority programmes, newest designations first, Latin names only."""
        with SessionLocal() as db:
            rows = db.execute(
                select(SanctionsEntity.id, SanctionsEntity.name, SanctionsEntity.programs)
                .where(SanctionsEntity.is_active.is_(True), SanctionsEntity.entity_type == "company", SanctionsEntity.designating_authority == "OFAC")
                .order_by(SanctionsEntity.designation_date.desc().nulls_last()).limit(3000)
            ).all()
        picked = []
        for r in rows:
            programs = " ".join(r.programs or [])
            if any(p in programs for p in PRIORITY_PROGRAMS) and latin_enough(r.name) and len(core_name(r.name)) >= 5:
                picked.append((r.id, r.name))
        return picked[:600]

    @staticmethod
    def _store(records: list[legal.LegalRecord], entity_id: int | None) -> dict[str, int]:
        with SessionLocal() as db:
            existing = {(s, i) for s, i in db.execute(select(LegalEvent.source, LegalEvent.source_id)).all()}
            entity = db.get(SanctionsEntity, entity_id) if entity_id else None
            inserted = 0
            for record in records:
                if (record.source, record.source_id) in existing:
                    continue
                if record.source == "courtlistener" and entity is not None:
                    core = core_name(entity.name)
                    haystack = " ".join([record.title, *record.parties]).upper()
                    if core and core not in haystack:
                        continue  # the phrase search matched a filing body, not a party - skip
                db.add(LegalEvent(source=record.source, source_id=record.source_id, title=record.title, url=record.url, court=record.court, event_date=record.event_date, discovered_at=utcnow(),
                                  event_type=record.event_type, matched_entity_id=entity.id if entity else None, matched_entity_name=entity.name if entity else None, query_used=record.details.get("query") if record.details else None,
                                  summary=record.summary, penalty_usd=record.penalty_usd, relevance_score=0.9 if entity else 0.6 if record.source == "ofac_enforcement" else 0.5,
                                  details={**(record.details or {}), "parties": record.parties[:40]}))
                existing.add((record.source, record.source_id))
                inserted += 1
            db.commit()
            return {"inserted": inserted}

    @staticmethod
    def summary(db: Session, days: int = 90) -> dict[str, Any]:
        since = utcnow() - timedelta(days=days)
        total = db.execute(select(func.count(LegalEvent.id)).where(or_(LegalEvent.event_date >= since, LegalEvent.discovered_at >= since))).scalar() or 0
        by_source = dict(db.execute(select(LegalEvent.source, func.count()).where(or_(LegalEvent.event_date >= since, LegalEvent.discovered_at >= since)).group_by(LegalEvent.source)).all())
        penalties = db.execute(select(func.sum(LegalEvent.penalty_usd)).where(LegalEvent.event_date >= since)).scalar() or 0.0
        matched = db.execute(select(func.count(LegalEvent.id)).where(LegalEvent.matched_entity_id.is_not(None))).scalar() or 0
        return {"days": days, "events": total, "by_source": by_source, "penalties_usd": round(penalties), "docket_matches_total": matched}


legal_bot = LegalBot()
