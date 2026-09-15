"""Disinformation / narrative monitor (ecosystem tier 2).

State-media headlines already collected by the geopolitical bot (RT, TASS,
Global Times - ``keywords`` carry ``state_media``) are clustered on shared
distinctive tokens inside a rolling window.  A story pushed by several state
outlets that official / non-state feeds do not carry is a ``state_only``
narrative; one pushed far harder than elsewhere is ``amplified``.
"""

import asyncio
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import cast, func, select, String
from sqlalchemy.orm import Session

from app.analysis.tier2 import cluster_narratives, narrative_assessment, topic_tokens
from app.database import SessionLocal
from app.models.geopolitical import GeopoliticalEvent
from app.models.tier2 import Narrative
from app.utils import config_store
from app.utils.logger import logger
from app.utils.time import utcnow

log = logger.bind(component="narratives")


def _config() -> dict[str, Any]:
    return config_store.get_config().get("narratives", {})


class NarrativeBot:
    def __init__(self) -> None:
        self.last_run: datetime | None = None
        self.last_result: dict[str, Any] = {}

    def status(self) -> dict[str, Any]:
        return {"last_run": self.last_run, "last_result": self.last_result}

    async def run(self) -> dict[str, Any]:
        cfg = _config()
        if not cfg.get("enabled", True):
            return {"skipped": "disabled"}
        result = await asyncio.to_thread(self._run, int(cfg.get("window_hours", 36)), int(cfg.get("min_items", 3)))
        self.last_run = utcnow()
        self.last_result = result
        log.info("narratives: {}", result)
        return result

    @staticmethod
    def _run(window_hours: int, min_items: int) -> dict[str, Any]:
        since = utcnow() - timedelta(hours=window_hours)
        with SessionLocal() as db:
            rows = db.execute(select(GeopoliticalEvent).where(GeopoliticalEvent.detected_date >= since, cast(GeopoliticalEvent.keywords, String).like('%"state_media"%'))).scalars().all()
            state_items = [{"title": r.title, "outlet": r.source, "time": r.event_date, "url": (r.source_urls or [None])[0], "countries": r.affected_countries or []} for r in rows]
            others = db.execute(select(GeopoliticalEvent.title).where(GeopoliticalEvent.detected_date >= since, ~cast(GeopoliticalEvent.keywords, String).like('%"state_media"%'))).scalars().all()
            other_tokens = [set(topic_tokens(t)) for t in others]
            candidates = cluster_narratives(state_items, min_items=min_items)
            existing = {n.fingerprint: n for n in db.execute(select(Narrative).where(Narrative.last_seen >= since - timedelta(days=2))).scalars()}
            created = updated = 0
            for cand in candidates:
                keyset = set(cand.keywords[:4])
                western = sum(1 for toks in other_tokens if len(toks & keyset) >= 2)
                score, divergence, severity, text = narrative_assessment(cand, western)
                row = existing.get(cand.fingerprint)
                payload = dict(topic=cand.topic[:300], keywords=cand.keywords, outlets=cand.outlets, outlet_count=len(cand.outlets), item_count=len(cand.items), countries=cand.countries,
                               sample_titles=[m["title"][:200] for m in cand.items[:6]], sample_urls=[m["url"] for m in cand.items[:6] if m.get("url")], first_seen=cand.first_seen, last_seen=cand.last_seen,
                               western_coverage=western, divergence=divergence, score=score, severity=severity, assessment=text)
                if row is None:
                    db.add(Narrative(fingerprint=cand.fingerprint, detected_at=utcnow(), **payload))
                    created += 1
                elif row.item_count != len(cand.items) or row.western_coverage != western:
                    for key, value in payload.items():
                        setattr(row, key, value)
                    updated += 1
            db.commit()
        return {"state_items": len(state_items), "other_items": len(others), "narratives": len(candidates), "created": created, "updated": updated}

    @staticmethod
    def summary(db: Session, days: int = 7) -> dict[str, Any]:
        since = utcnow() - timedelta(days=days)
        rows = db.execute(select(Narrative).where(Narrative.last_seen >= since)).scalars().all()
        by_div = {}
        for r in rows:
            by_div[r.divergence] = by_div.get(r.divergence, 0) + 1
        outlets: dict[str, int] = {}
        for r in rows:
            for k, v in (r.outlets or {}).items():
                outlets[k] = outlets.get(k, 0) + v
        state_items = db.execute(select(func.count(GeopoliticalEvent.id)).where(GeopoliticalEvent.detected_date >= since, cast(GeopoliticalEvent.keywords, String).like('%"state_media"%'))).scalar() or 0
        return {"days": days, "narratives": len(rows), "by_divergence": by_div, "outlet_items": outlets, "state_media_items": state_items,
                "top": [{"id": r.id, "topic": r.topic, "divergence": r.divergence, "score": r.score, "items": r.item_count, "outlets": r.outlet_count, "last_seen": r.last_seen} for r in sorted(rows, key=lambda n: -(n.score or 0))[:6]]}


narrative_bot = NarrativeBot()
