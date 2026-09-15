"""Sanctions monitoring bot (Phase 2.5) - the fusion point between the lists and the other bots.

* ``update_all_sanctions`` - download OFAC / EU / UN, diff against the database,
  upsert, record ``SanctionsUpdate`` rows, refresh programme counts, audit-log.
* ``check_vessel`` / ``check_entity`` - screening through the in-memory index.
* ``generate_report`` - recent-activity summary for analysts.
"""

import asyncio
from collections import Counter
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import bindparam, func, select
from sqlalchemy.orm import Session

from app.analysis.sanctions import ListChanges, Match, SanctionsIndex, compare_sanctions_lists
from app.database import SessionLocal
from app.integrations import eu_sanctions, ofac, un_sanctions
from app.integrations.sanctions_common import SanctionedEntityRecord, normalize_name
from app.models.audit import AuditLog
from app.models.sanctions import SanctionsEntity, SanctionsProgramTracking, SanctionsUpdate
from app.utils.logger import logger
from app.utils.time import utcnow

log = logger.bind(component="sanctions")

FETCHERS = {"OFAC": ofac.load_ofac_list, "EU": eu_sanctions.load_eu_list, "UN": un_sanctions.load_un_list}


def _record_to_row(record: SanctionedEntityRecord) -> dict[str, Any]:
    return {
        "designating_authority": record.authority,
        "source_id": record.source_id,
        "name": record.name[:300],
        "name_normalized": normalize_name(record.name)[:300],
        "entity_type": record.entity_type,
        "un_committee": record.un_committee,
        "country_linked": record.country,
        "designation_date": record.designation_date,
        "programs": record.programs,
        "addresses": record.addresses,
        "aliases": record.aliases,
        "imo": record.imo,
        "call_sign": record.call_sign,
        "vessel_flag": record.vessel_flag,
        "vessel_owner": record.vessel_owner[:300] if record.vessel_owner else None,
        "vessel_type": (record.vessel_type or None) and record.vessel_type[:100],
        "remarks": record.remarks,
        "is_active": True,
        "delisting_date": None,
        "last_updated": utcnow(),
        "source_url": record.source_url,
    }


class SanctionsMonitoringBot:
    def __init__(self) -> None:
        self.index: SanctionsIndex | None = None
        self.last_refresh: dict[str, datetime] = {}
        self.last_result: dict[str, dict[str, Any]] = {}
        self.refreshing = False
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------ refreshing
    async def update_all_sanctions(self, authorities: list[str] | None = None) -> dict[str, dict[str, Any]]:
        """Fetch every list, apply changes, rebuild the index.  Safe to call repeatedly."""
        async with self._lock:
            self.refreshing = True
            results: dict[str, dict[str, Any]] = {}
            try:
                for authority in authorities or list(FETCHERS):
                    try:
                        records = await FETCHERS[authority]()
                        summary = await asyncio.to_thread(self._apply, authority, records)
                        self.last_refresh[authority] = utcnow()
                        results[authority] = summary
                        log.info("{} refresh: {}", authority, summary)
                    except Exception as exc:  # noqa: BLE001 - one failing list must not block the others
                        log.exception("{} refresh failed: {}", authority, exc)
                        results[authority] = {"error": str(exc)}
                self.last_result.update(results)
                await asyncio.to_thread(self.rebuild_index)
            finally:
                self.refreshing = False
            return results

    @staticmethod
    def _apply(authority: str, records: list[SanctionedEntityRecord]) -> dict[str, Any]:
        with SessionLocal() as db:
            rows = db.execute(
                select(SanctionsEntity.id, SanctionsEntity.source_id, SanctionsEntity.name, SanctionsEntity.programs, SanctionsEntity.imo, SanctionsEntity.is_active)
                .where(SanctionsEntity.designating_authority == authority)
            ).all()
            existing = {r.source_id: {"id": r.id, "source_id": r.source_id, "name": r.name, "programs": r.programs, "imo": r.imo, "is_active": r.is_active} for r in rows}
            changes = compare_sanctions_lists(existing, records, authority)
            initial_import = not existing
            now = utcnow()

            if changes.new:
                db.execute(SanctionsEntity.__table__.insert(), [{**_record_to_row(r), "first_seen_at": now} for r in changes.new])
            if changes.relisted:
                db.execute(SanctionsEntity.__table__.update().where(SanctionsEntity.id == bindparam("_id")),
                           [{"_id": entity_id, **_record_to_row(r)} for entity_id, r in changes.relisted])
            if changes.changed:
                db.execute(SanctionsEntity.__table__.update().where(SanctionsEntity.id == bindparam("_id")),
                           [{"_id": entity_id, **_record_to_row(r)} for entity_id, r, _ in changes.changed])
            if changes.delisted:
                db.execute(SanctionsEntity.__table__.update().where(SanctionsEntity.id == bindparam("_id")),
                           [{"_id": row["id"], "is_active": False, "delisting_date": now, "last_updated": now} for row in changes.delisted])
            db.flush()
            SanctionsMonitoringBot._record_updates(db, authority, changes, initial_import, now)
            SanctionsMonitoringBot._update_program_tracking(db, authority, now)
            summary = {
                "fetched": len(records),
                "new": len(changes.new),
                "relisted": len(changes.relisted),
                "changed": len(changes.changed),
                "delisted": len(changes.delisted),
                "unchanged": changes.unchanged,
                "initial_import": initial_import,
                "delisting_skipped": changes.skipped_delisting,
            }
            db.add(
                AuditLog(
                    action_type="sanctions_list_refreshed",
                    user_id="system",
                    sanctioning_authorities=[authority],
                    rationale=f"{authority} list refreshed: {len(records)} entries fetched",
                    supporting_data=summary,
                    source_systems=["bots.sanctions"],
                    created_by="system",
                )
            )
            db.commit()
            return summary

    @staticmethod
    def _record_updates(db: Session, authority: str, changes: ListChanges, initial_import: bool, now: datetime) -> None:
        if initial_import:
            db.add(SanctionsUpdate(timestamp=now, authority=authority, update_type="initial_import", entity_name=f"{len(changes.new)} listings imported",
                                   new_status={"count": len(changes.new)}, processed=True))
            return
        new_ids = dict(db.execute(select(SanctionsEntity.source_id, SanctionsEntity.id).where(
            SanctionsEntity.designating_authority == authority, SanctionsEntity.first_seen_at >= now)).all())
        updates = []
        for record in changes.new:
            updates.append(SanctionsUpdate(timestamp=now, authority=authority, update_type="new_designation", entity_id=new_ids.get(record.source_id),
                                           entity_name=record.name[:300], entity_type=record.entity_type, new_status={"programs": record.programs, "imo": record.imo},
                                           source_url=record.source_url))
        for entity_id, record in changes.relisted:
            updates.append(SanctionsUpdate(timestamp=now, authority=authority, update_type="relisted", entity_id=entity_id, entity_name=record.name[:300],
                                           entity_type=record.entity_type, previous_status={"status": "delisted"}, new_status={"status": "active", "programs": record.programs}))
        for entity_id, record, diff in changes.changed:
            kind = "name_change" if "name" in diff else "program_change" if "programs" in diff else "identifier_change"
            updates.append(SanctionsUpdate(timestamp=now, authority=authority, update_type=kind, entity_id=entity_id, entity_name=record.name[:300],
                                           entity_type=record.entity_type, previous_status={k: v[0] for k, v in diff.items()}, new_status={k: v[1] for k, v in diff.items()}))
        for row in changes.delisted:
            updates.append(SanctionsUpdate(timestamp=now, authority=authority, update_type="delisting", entity_id=row["id"], entity_name=row["name"][:300],
                                           previous_status={"status": "active"}, new_status={"status": "delisted"}))
        db.add_all(updates)

    @staticmethod
    def _update_program_tracking(db: Session, authority: str, now: datetime) -> None:
        rows = db.execute(select(SanctionsEntity.programs, SanctionsEntity.entity_type).where(
            SanctionsEntity.designating_authority == authority, SanctionsEntity.is_active.is_(True))).all()
        entities, vessels = Counter(), Counter()
        for programs, entity_type in rows:
            for program in programs or ["(unspecified)"]:
                entities[program] += 1
                if entity_type == "vessel":
                    vessels[program] += 1
        existing = {t.program_name: t for t in db.execute(select(SanctionsProgramTracking).where(SanctionsProgramTracking.authority == authority)).scalars()}
        for program, count in entities.items():
            tracking = existing.get(program) or SanctionsProgramTracking(authority=authority, program_name=program)
            tracking.entities_in_program = count
            tracking.vessels_in_program = vessels.get(program, 0)
            tracking.last_updated = now
            db.add(tracking)

    # ----------------------------------------------------------------- index
    def rebuild_index(self) -> SanctionsIndex:
        with SessionLocal() as db:
            rows = db.execute(select(SanctionsEntity).where(SanctionsEntity.is_active.is_(True))).scalars().all()
            self.index = SanctionsIndex(rows)
        log.info("sanctions index rebuilt: {} active listings", len(self.index))
        return self.index

    def ensure_index(self) -> SanctionsIndex:
        if self.index is None:
            self.rebuild_index()
        return self.index

    # --------------------------------------------------------------- screens
    def check_vessel(self, vessel, min_confidence: float = 0.0) -> list[Match]:
        return [m for m in self.ensure_index().match_vessel(vessel) if m.confidence >= min_confidence]

    def check_entity(self, name: str, entity_type: str | None = None, min_similarity: float = 0.85) -> list[Match]:
        types = {entity_type} if entity_type else None
        return self.ensure_index().match_name(name, types, min_similarity)

    # ---------------------------------------------------------------- report
    @staticmethod
    def generate_report(days: int = 7, authorities: list[str] | None = None) -> dict[str, Any]:
        since = utcnow() - timedelta(days=days)
        with SessionLocal() as db:
            query = select(SanctionsUpdate).where(SanctionsUpdate.timestamp >= since)
            if authorities:
                query = query.where(SanctionsUpdate.authority.in_(authorities))
            updates = db.execute(query.order_by(SanctionsUpdate.timestamp.desc())).scalars().all()
            active = dict(db.execute(select(SanctionsEntity.designating_authority, func.count()).where(SanctionsEntity.is_active.is_(True)).group_by(SanctionsEntity.designating_authority)).all())
            vessels = dict(db.execute(select(SanctionsEntity.designating_authority, func.count()).where(
                SanctionsEntity.is_active.is_(True), SanctionsEntity.entity_type == "vessel").group_by(SanctionsEntity.designating_authority)).all())
        summary: dict[str, dict[str, int]] = {}
        for update in updates:
            summary.setdefault(update.authority, {})
            summary[update.authority][update.update_type] = summary[update.authority].get(update.update_type, 0) + 1
        return {
            "period_days": days,
            "generated_at": utcnow(),
            "active_listings": active,
            "active_vessels": vessels,
            "total_updates": len(updates),
            "summary": summary,
            "updates": [
                {"timestamp": u.timestamp, "authority": u.authority, "type": u.update_type, "entity_id": u.entity_id, "entity_name": u.entity_name,
                 "entity_type": u.entity_type, "previous": u.previous_status, "new": u.new_status, "source_url": u.source_url}
                for u in updates[:500]
            ],
        }

    def status(self) -> dict[str, Any]:
        with SessionLocal() as db:
            counts = dict(db.execute(select(SanctionsEntity.designating_authority, func.count()).where(SanctionsEntity.is_active.is_(True)).group_by(SanctionsEntity.designating_authority)).all())
            last_update = db.execute(select(func.max(SanctionsUpdate.timestamp))).scalar()
        return {
            "refreshing": self.refreshing,
            "last_refresh": self.last_refresh,
            "last_result": self.last_result,
            "active_listings": counts,
            "index_size": len(self.index) if self.index else 0,
            "index_built_at": self.index.built_at if self.index else None,
            "last_update_recorded": last_update,
        }


sanctions_bot = SanctionsMonitoringBot()
