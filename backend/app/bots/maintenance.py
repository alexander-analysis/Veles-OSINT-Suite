"""Retention for the ecosystem tables (the audit log is never purged)."""

import asyncio
import ctypes
import gc
import platform
from datetime import timedelta
from typing import Any

from sqlalchemy import delete

from app.database import SessionLocal, checkpoint_wal
from app.models.correlation import CompositeAlert, SignalCorrelation
from app.models.energy import DarkOilIndicator, EnergyFlowSnapshot, OilTankerShipment
from app.models.geopolitical import EventCorrelation
from app.models.tier2 import AircraftSighting, BreachEvent, LegalEvent, Narrative
from app.utils import config_store
from app.utils.logger import logger
from app.utils.time import utcnow

log = logger.bind(component="maintenance")

DEFAULTS = {
    "signal_correlations_days": 30,
    "composite_alerts_days": 180,
    "aircraft_sightings_days": 90,
    "breach_events_days": 180,
    "narratives_days": 90,
    "legal_events_days": 365,
    "energy_days": 180,
}


async def purge_ecosystem_tables() -> dict[str, int]:
    cfg = config_store.get_config().get("retention", {})
    now = utcnow()

    def days(key: str) -> timedelta:
        return timedelta(days=int(cfg.get(key, DEFAULTS[key])))

    def _run() -> dict[str, int]:
        out: dict[str, int] = {}
        with SessionLocal() as db:
            out["signal_correlations"] = db.execute(delete(SignalCorrelation).where(SignalCorrelation.detected_at < now - days("signal_correlations_days"))).rowcount
            out["composite_alerts"] = db.execute(delete(CompositeAlert).where(CompositeAlert.detected_at < now - days("composite_alerts_days"), CompositeAlert.acknowledged.is_(True))).rowcount
            out["event_correlations"] = db.execute(delete(EventCorrelation).where(EventCorrelation.detected_at < now - days("signal_correlations_days"))).rowcount
            out["aircraft_sightings"] = db.execute(delete(AircraftSighting).where(AircraftSighting.timestamp < now - days("aircraft_sightings_days"))).rowcount
            out["breach_events"] = db.execute(delete(BreachEvent).where(BreachEvent.discovered_at < now - days("breach_events_days"), BreachEvent.matched_company_id.is_(None))).rowcount
            out["narratives"] = db.execute(delete(Narrative).where(Narrative.last_seen < now - days("narratives_days"))).rowcount
            out["legal_events"] = db.execute(delete(LegalEvent).where(LegalEvent.discovered_at < now - days("legal_events_days"), LegalEvent.matched_entity_id.is_(None))).rowcount
            out["energy_snapshots"] = db.execute(delete(EnergyFlowSnapshot).where(EnergyFlowSnapshot.day < now - days("energy_days"))).rowcount
            out["dark_oil_cleared"] = db.execute(delete(DarkOilIndicator).where(DarkOilIndicator.detected_at < now - days("energy_days"), DarkOilIndicator.investigation_status == "cleared")).rowcount
            out["shipments_stale"] = db.execute(delete(OilTankerShipment).where(OilTankerShipment.loading_date < now - days("energy_days"), OilTankerShipment.dark_oil_suspect.is_(False))).rowcount
            db.commit()
        return out

    result = await asyncio.to_thread(_run)
    log.info("retention purge: {}", {k: v for k, v in result.items() if v})
    return result


async def checkpoint() -> dict[str, int] | None:
    """PASSIVE first (never blocks), then TRUNCATE when the WAL is large - readers are short-lived, so it usually completes."""
    result = await asyncio.to_thread(checkpoint_wal, "PASSIVE")
    if result and result["wal_pages"] > 20_000:
        result = await asyncio.to_thread(checkpoint_wal, "TRUNCATE")
    if result and result["wal_pages"] > 20_000:
        log.info("wal checkpoint: {}", result)
    return result


async def trim_memory() -> dict[str, int]:
    """Collect garbage and hand freed heap back to the OS (glibc keeps it otherwise - RSS crept to 1 GB on the Pi)."""
    collected = gc.collect()
    trimmed = 0
    if platform.system() == "Linux":
        try:
            trimmed = int(ctypes.CDLL("libc.so.6").malloc_trim(0))
        except (OSError, AttributeError):
            trimmed = 0
    return {"collected": collected, "trimmed": trimmed}


def register(scheduler, on_loop, purge_hour: int) -> Any:
    scheduler.add_job(on_loop(checkpoint, timeout=600), "interval", minutes=10, id="maintenance.checkpoint", replace_existing=True)
    scheduler.add_job(on_loop(trim_memory, timeout=60), "interval", minutes=15, id="maintenance.trim_memory", replace_existing=True)
    return scheduler.add_job(on_loop(purge_ecosystem_tables, timeout=900), "cron", hour=purge_hour, minute=55, id="maintenance.purge", replace_existing=True)
