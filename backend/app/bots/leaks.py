"""Leak & breach monitor (ecosystem tier 2).

ransomware.live victim postings and the HIBP breach catalogue are matched against
tracked companies, sanctions listings, critical sectors and watch keywords; the
relevant ones are stored as ``BreachEvent`` rows and feed the fusion engine.
"""

import asyncio
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.analysis.tier2 import CompanyIndex, breach_relevance
from app.database import SessionLocal
from app.integrations import leaks
from app.models.corporate import Company
from app.models.tier2 import BreachEvent
from app.utils import config_store
from app.utils.logger import logger
from app.utils.time import utcnow

log = logger.bind(component="leaks")


def _config() -> dict[str, Any]:
    return config_store.get_config().get("leaks", {})


class LeaksBot:
    def __init__(self) -> None:
        self.last_run: dict[str, datetime] = {}
        self.last_result: dict[str, Any] = {}

    def status(self) -> dict[str, Any]:
        return {"last_run": dict(self.last_run), "last_result": self.last_result}

    async def fetch(self) -> dict[str, Any]:
        cfg = _config()
        if not cfg.get("enabled", True):
            return {"skipped": "disabled"}
        records: list[leaks.BreachRecord] = []
        outcome: dict[str, Any] = {}
        for name, fetcher in (("ransomware_live", leaks.fetch_ransomware_recent), ("hibp", leaks.fetch_hibp_breaches)):
            if not cfg.get(f"{name}_enabled", True):
                continue
            try:
                rows = await fetcher()
                records.extend(rows)
                outcome[name] = len(rows)
            except Exception as exc:  # noqa: BLE001
                outcome[name] = f"error: {exc}"[:120]
                log.warning("{} failed: {}", name, exc)
        stored = await asyncio.to_thread(self._store, records, [str(k) for k in cfg.get("watch_keywords", [])], float(cfg.get("min_store_score", 0.5)))
        result = {**outcome, **stored}
        self.last_run["fetch"] = utcnow()
        self.last_result["fetch"] = result
        log.info("leaks: {}", result)
        return result

    @staticmethod
    def _store(records: list[leaks.BreachRecord], watch_keywords: list[str], min_score: float) -> dict[str, int]:
        with SessionLocal() as db:
            existing = {(s, i) for s, i in db.execute(select(BreachEvent.source, BreachEvent.source_id)).all()}
            companies = db.execute(select(Company.id, Company.company_name, Company.registration_country, Company.sanctioned_entity_id).where(Company.linked_to_sanctioned.is_(True)).limit(20000)).all()
            index = CompanyIndex([(c.id, c.company_name, c.registration_country) for c in companies])
            entity_by_company = {c.id: c.sanctioned_entity_id for c in companies}
            inserted = skipped = 0
            for record in records:
                if (record.source, record.source_id) in existing:
                    continue
                company_id, strength = index.match(record.victim_name, record.country)
                strong = strength == "strong"
                entity_id = entity_by_company.get(company_id) if company_id and strong else None
                assessment = breach_relevance(record.victim_name, record.victim_domain, record.country, record.sector, strong, entity_id is not None, watch_keywords, record.records_affected)
                if company_id and not strong:
                    assessment.reasons.append(f"possible name match (unverified): {index.names[company_id]}")
                    if assessment.score < 0.55:
                        assessment.score, assessment.severity = 0.55, "medium"
                    company_id = None
                if assessment.score < min_score:
                    skipped += 1
                    existing.add((record.source, record.source_id))
                    continue
                db.add(BreachEvent(source=record.source, source_id=record.source_id, victim_name=record.victim_name, victim_domain=record.victim_domain, country=record.country, sector=record.sector,
                                   threat_actor=record.threat_actor, event_date=record.event_date, discovered_at=utcnow(), description=record.description, url=record.url, records_affected=record.records_affected,
                                   data_classes=record.data_classes, matched_company_id=company_id, matched_entity_id=entity_id, relevance=assessment.relevance, relevance_score=assessment.score,
                                   severity=assessment.severity, details={**record.details, "reasons": assessment.reasons}))
                existing.add((record.source, record.source_id))
                inserted += 1
                if assessment.severity in ("high", "critical"):
                    from app import notifications

                    notifications.send_alert("leaks", f"Breach: {record.victim_name}", f"{assessment.relevance.replace('_', ' ')} - {record.threat_actor or record.source} - {'; '.join(assessment.reasons)}", severity=assessment.severity,
                                             data={"victim": record.victim_name, "source": record.source})
            db.commit()
            return {"inserted": inserted, "below_threshold": skipped}

    @staticmethod
    def summary(db: Session, days: int = 30) -> dict[str, Any]:
        since = utcnow() - timedelta(days=days)
        total = db.execute(select(func.count(BreachEvent.id)).where(BreachEvent.discovered_at >= since)).scalar() or 0
        by_relevance = dict(db.execute(select(BreachEvent.relevance, func.count()).where(BreachEvent.discovered_at >= since).group_by(BreachEvent.relevance)).all())
        by_actor = db.execute(select(BreachEvent.threat_actor, func.count()).where(BreachEvent.discovered_at >= since, BreachEvent.threat_actor.is_not(None)).group_by(BreachEvent.threat_actor).order_by(func.count().desc()).limit(8)).all()
        by_country = db.execute(select(BreachEvent.country, func.count()).where(BreachEvent.discovered_at >= since, BreachEvent.country.is_not(None)).group_by(BreachEvent.country).order_by(func.count().desc()).limit(8)).all()
        tracked = db.execute(select(func.count(BreachEvent.id)).where(BreachEvent.discovered_at >= since, BreachEvent.matched_company_id.is_not(None))).scalar() or 0
        return {"days": days, "events": total, "by_relevance": by_relevance, "tracked_company_hits": tracked, "top_actors": [{"actor": a, "events": n} for a, n in by_actor], "top_countries": [{"country": c, "events": n} for c, n in by_country]}


leaks_bot = LeaksBot()
