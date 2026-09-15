"""Port State Control monitor (ecosystem tier 2 - port authority data).

Paris MoU current detentions and bannings (THETIS public REST) and the Tokyo MoU
monthly detention list (APCIS) are stored as ``PscEvent`` rows keyed by IMO, joined
to our vessel records and flagged when the hull is already sanctioned / high risk
or is a tanker trading sanctioned routes.  Detentions feed the vessel risk score
and the fusion engine.
"""

import asyncio
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.integrations import psc
from app.models.audit import AuditLog
from app.models.energy import OilTankerShipment
from app.models.maritime import Vessel
from app.models.tier2 import PscEvent
from app.utils import config_store
from app.utils.logger import logger
from app.utils.time import utcnow

log = logger.bind(component="psc")


def _config() -> dict[str, Any]:
    return config_store.get_config().get("psc", {})


class PscBot:
    def __init__(self) -> None:
        self.last_run: datetime | None = None
        self.last_result: dict[str, Any] = {}

    def status(self) -> dict[str, Any]:
        return {"last_run": self.last_run, "last_result": self.last_result}

    async def fetch(self) -> dict[str, Any]:
        cfg = _config()
        if not cfg.get("enabled", True):
            return {"skipped": "disabled"}
        records: list[psc.PscRecord] = []
        outcome: dict[str, Any] = {}
        if cfg.get("paris_enabled", True):
            try:
                detentions, bans = await psc.fetch_paris()
                records.extend(detentions)
                records.extend(bans)
                outcome["paris_mou"] = {"detentions": len(detentions), "bans": len(bans)}
            except Exception as exc:  # noqa: BLE001
                outcome["paris_mou"] = f"error: {exc}"[:120]
                log.warning("paris mou failed: {}", exc)
        if cfg.get("tokyo_enabled", True):
            now = utcnow()
            months = [(now.year, now.month)]
            if now.day <= 7:  # the previous month is still being completed early in the month
                prev = (now.replace(day=1) - timedelta(days=1))
                months.append((prev.year, prev.month))
            for year, month in months:
                try:
                    rows = await psc.fetch_tokyo(year, month)
                    records.extend(rows)
                    outcome[f"tokyo_mou_{year}_{month:02d}"] = len(rows)
                except Exception as exc:  # noqa: BLE001
                    outcome[f"tokyo_mou_{year}_{month:02d}"] = f"error: {exc}"[:120]
                    log.warning("tokyo mou {}-{} failed: {}", year, month, exc)
        stored = await asyncio.to_thread(self._store, records)
        result = {**outcome, **stored}
        self.last_run = utcnow()
        self.last_result = result
        log.info("psc: {}", result)
        return result

    @staticmethod
    def _store(records: list[psc.PscRecord]) -> dict[str, int]:
        with SessionLocal() as db:
            existing = {(s, i) for s, i in db.execute(select(PscEvent.source, PscEvent.source_id)).all()}
            imos = list({r.imo for r in records if r.imo})
            vessels: dict[str, Vessel] = {}
            for i in range(0, len(imos), 500):
                for v in db.execute(select(Vessel).where(Vessel.imo.in_(imos[i:i + 500]))).scalars():
                    vessels[v.imo] = v
            vessel_ids = [v.id for v in vessels.values()]
            sanctioned_routes: set[int] = set()
            for i in range(0, len(vessel_ids), 500):
                sanctioned_routes.update(vid for (vid,) in db.execute(select(OilTankerShipment.vessel_id).where(OilTankerShipment.vessel_id.in_(vessel_ids[i:i + 500]), OilTankerShipment.sanctioned_route.is_(True))).all())
            inserted = matched = flagged = 0
            for record in records:
                if (record.source, record.source_id) in existing:
                    continue
                vessel = vessels.get(record.imo) if record.imo else None
                is_tanker = bool(record.ship_type and "tank" in record.ship_type.lower()) or bool(vessel and "tank" in (vessel.ship_type or "").lower())
                vessel_flagged = bool(vessel and ((vessel.sanctioned_status or "clear") != "clear" or (vessel.risk_score or 0) >= 0.5 or vessel.id in sanctioned_routes))
                score = 0.3 + (0.2 if record.event_type == "ban" else 0.0) + (0.15 if is_tanker else 0.0) + (0.15 if vessel else 0.0) + (0.4 if vessel_flagged else 0.0)
                score = round(min(score, 1.0), 2)
                db.add(PscEvent(source=record.source, source_id=record.source_id, event_type=record.event_type, imo=record.imo, ship_name=record.ship_name, flag=record.flag, ship_type=record.ship_type,
                                gross_tonnage=record.gross_tonnage, year_built=record.year_built, company=record.company, class_society=record.class_society, port=record.port, port_country=record.port_country,
                                event_date=record.event_date, release_date=record.release_date, deficiencies=record.deficiencies, deficiency_count=len(record.deficiencies), vessel_id=vessel.id if vessel else None,
                                vessel_flagged=vessel_flagged, relevance_score=score, discovered_at=utcnow(), details=record.details))
                existing.add((record.source, record.source_id))
                inserted += 1
                matched += bool(vessel)
                if vessel_flagged:
                    flagged += 1
                    db.add(AuditLog(action_type="psc_detention_flagged_vessel", user_id="system", vessel_id=vessel.id, rationale=f"{record.ship_name} ({record.flag}) {record.event_type} by {record.source.replace('_', ' ')} at {record.port or '-'} - vessel already {vessel.sanctioned_status} / risk {vessel.risk_score}",
                                    supporting_data={"imo": record.imo, "port": record.port, "deficiencies": record.deficiencies[:10]}, source_systems=["bots.psc"], created_by="system"))
            db.commit()
            return {"inserted": inserted, "matched_vessels": matched, "flagged": flagged}

    @staticmethod
    def summary(db: Session, days: int = 30) -> dict[str, Any]:
        since = utcnow() - timedelta(days=days)
        total = db.execute(select(func.count(PscEvent.id)).where(PscEvent.event_date >= since)).scalar() or 0
        by_type = dict(db.execute(select(PscEvent.event_type, func.count()).where(PscEvent.event_date >= since).group_by(PscEvent.event_type)).all())
        by_source = dict(db.execute(select(PscEvent.source, func.count()).where(PscEvent.event_date >= since).group_by(PscEvent.source)).all())
        by_flag = db.execute(select(PscEvent.flag, func.count()).where(PscEvent.event_date >= since, PscEvent.flag.is_not(None)).group_by(PscEvent.flag).order_by(func.count().desc()).limit(8)).all()
        matched = db.execute(select(func.count(PscEvent.id)).where(PscEvent.event_date >= since, PscEvent.vessel_id.is_not(None))).scalar() or 0
        flagged = db.execute(select(func.count(PscEvent.id)).where(PscEvent.event_date >= since, PscEvent.vessel_flagged.is_(True))).scalar() or 0
        bans_active = db.execute(select(func.count(PscEvent.id)).where(PscEvent.event_type == "ban")).scalar() or 0
        return {"days": days, "events": total, "by_type": by_type, "by_source": by_source, "top_flags": [{"flag": f, "events": n} for f, n in by_flag], "matched_vessels": matched, "flagged_vessels": flagged, "bans_on_record": bans_active}


psc_bot = PscBot()
