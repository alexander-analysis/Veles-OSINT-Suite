"""APScheduler wiring for the perpetual bots.

Phase 1 registers only a heartbeat so the scheduler path is exercised end to
end.  Phase 2 adds the market jobs (candle fetch / analysis / cleanup) and
Phase 3 the maritime jobs (AIS poll / sanctions checks / list refresh).

Job defaults are tuned for a Pi: a slow run is never overlapped by the next
one (``max_instances=1``) and missed runs collapse into one (``coalesce``).
"""

from typing import Any

from apscheduler.schedulers.background import BackgroundScheduler

from app.utils.logger import logger

log = logger.bind(component="scheduler")

scheduler = BackgroundScheduler(
    timezone="UTC",
    job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": 60},
)


def _heartbeat() -> None:
    log.info("heartbeat - {} job(s) registered", len(scheduler.get_jobs()))


def start_scheduler() -> BackgroundScheduler:
    """Register the standing jobs and start the scheduler (idempotent)."""
    if scheduler.running:
        return scheduler
    scheduler.add_job(_heartbeat, "interval", minutes=5, id="heartbeat", replace_existing=True)
    scheduler.start()
    log.info("started with {} job(s)", len(scheduler.get_jobs()))
    return scheduler


def stop_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
        log.info("stopped")


def scheduler_status() -> dict[str, Any]:
    """Snapshot for /api/health."""
    return {
        "running": scheduler.running,
        "jobs": [
            {"id": job.id, "next_run_time": job.next_run_time.replace(tzinfo=None) if job.next_run_time else None}
            for job in scheduler.get_jobs()
        ],
    }
