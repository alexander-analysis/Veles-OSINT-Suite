"""APScheduler wiring for the perpetual bots.

Bot coroutines run on the dedicated bot event loop (``app.bots.runtime``);
APScheduler worker threads only submit them and wait.  Job defaults are tuned
for a Pi: a slow run is never overlapped by the next one (``max_instances=1``)
and missed runs collapse into one (``coalesce``).

Cadences are read from ``settings.yaml`` when the scheduler starts; thresholds
are re-read by the bots on every run.
"""

from typing import Any

from apscheduler.schedulers.background import BackgroundScheduler

from app.bots.runtime import bot_loop
from app.utils import config_store
from app.utils.logger import logger

log = logger.bind(component="scheduler")

scheduler = BackgroundScheduler(
    timezone="UTC",
    job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": 60},
)


def _heartbeat() -> None:
    log.info("heartbeat - {} job(s) registered", len(scheduler.get_jobs()))


def _on_loop(coroutine_factory, timeout: float = 300):
    """Wrap an async bot method as a sync APScheduler job."""

    def job() -> None:
        try:
            bot_loop.run(coroutine_factory(), timeout=timeout)
        except Exception as exc:  # noqa: BLE001 - a failing job must not kill the scheduler
            log.exception("job {} failed: {}", getattr(coroutine_factory, "__name__", "?"), exc)

    job.__name__ = getattr(coroutine_factory, "__name__", "job")
    return job


def register_market_jobs() -> None:
    from app.bots.market import market_bot

    cfg = config_store.get_config()
    market = cfg.get("market", {})
    retention = cfg.get("retention", {})

    scheduler.add_job(
        _on_loop(market_bot.fetch_candles_all_exchanges),
        "interval",
        seconds=int(market.get("fetch_interval_seconds", 60)),
        id="market.fetch_candles",
        replace_existing=True,
    )
    scheduler.add_job(
        _on_loop(market_bot.fetch_commodities),
        "interval",
        minutes=5,
        id="market.fetch_commodities",
        replace_existing=True,
    )
    scheduler.add_job(
        _on_loop(market_bot.analyze_anomalies),
        "interval",
        minutes=int(market.get("analysis_interval_minutes", 5)),
        id="market.analyze_anomalies",
        replace_existing=True,
    )
    scheduler.add_job(
        _on_loop(market_bot.analyze_coordination),
        "interval",
        minutes=int(market.get("analysis_interval_minutes", 5)),
        id="market.analyze_coordination",
        replace_existing=True,
    )
    scheduler.add_job(
        _on_loop(market_bot.analyze_liquidations),
        "interval",
        minutes=int(market.get("analysis_interval_minutes", 5)),
        id="market.analyze_liquidations",
        replace_existing=True,
    )
    scheduler.add_job(
        _on_loop(market_bot.cleanup_old_data),
        "cron",
        hour=int(retention.get("purge_hour_utc", 2)),
        minute=0,
        id="market.cleanup_old_data",
        replace_existing=True,
    )
    # Warm up immediately instead of waiting a full interval after boot
    scheduler.add_job(_on_loop(market_bot.fetch_candles_all_exchanges), id="market.initial_fetch", replace_existing=True)
    scheduler.add_job(_on_loop(market_bot.fetch_commodities), id="market.initial_commodities", replace_existing=True)
    if market.get("liquidations_enabled", True):
        bot_loop.run(_start_liquidation_stream())


async def _start_liquidation_stream() -> None:
    from app.bots.market import market_bot

    market_bot.ensure_liquidation_stream()


def register_sanctions_jobs() -> None:
    from app.bots.sanctions import sanctions_bot

    cfg = config_store.get_config().get("sanctions", {})
    scheduler.add_job(
        _on_loop(sanctions_bot.update_all_sanctions, timeout=900),
        "interval",
        hours=int(cfg.get("refresh_interval_hours", 6)),
        id="sanctions.refresh_lists",
        replace_existing=True,
    )
    scheduler.add_job(
        _weekly_sanctions_report,
        "cron",
        day_of_week=int(cfg.get("weekly_report_day", 0)),
        hour=int(cfg.get("weekly_report_hour_utc", 9)),
        minute=0,
        id="sanctions.weekly_report",
        replace_existing=True,
    )
    if cfg.get("refresh_on_startup", True):
        # Load the lists right away on an empty database; otherwise just build the index
        from app.database import SessionLocal
        from app.models.sanctions import SanctionsEntity
        from sqlalchemy import func, select

        with SessionLocal() as db:
            listings = db.execute(select(func.count(SanctionsEntity.id)).where(SanctionsEntity.is_active.is_(True))).scalar() or 0
        if listings == 0:
            scheduler.add_job(_on_loop(sanctions_bot.update_all_sanctions, timeout=900), id="sanctions.initial_refresh", replace_existing=True)
        else:
            scheduler.add_job(sanctions_bot.rebuild_index, id="sanctions.initial_index", replace_existing=True)


def _weekly_sanctions_report() -> None:
    import json

    from app.bots.sanctions import sanctions_bot
    from app.config import BACKEND_DIR
    from app.database import SessionLocal
    from app.models.audit import AuditLog
    from app.utils.time import utcnow

    report = sanctions_bot.generate_report(days=7)
    reports_dir = BACKEND_DIR / "reports"
    reports_dir.mkdir(exist_ok=True)
    path = reports_dir / f"sanctions_weekly_{utcnow():%Y-%m-%d}.json"
    path.write_text(json.dumps(report, default=str, indent=2), encoding="utf-8")
    with SessionLocal() as db:
        db.add(AuditLog(action_type="report_generated", user_id="system", rationale="Weekly sanctions activity report",
                        supporting_data={"path": str(path), "updates": report["total_updates"]}, source_systems=["bots.sanctions"], created_by="system"))
        db.commit()
    log.info("weekly sanctions report written to {}", path)


def start_scheduler() -> BackgroundScheduler:
    """Register the standing jobs and start the scheduler (idempotent)."""
    if scheduler.running:
        return scheduler
    bot_loop.start()
    scheduler.add_job(_heartbeat, "interval", minutes=5, id="heartbeat", replace_existing=True)
    register_market_jobs()
    register_sanctions_jobs()
    scheduler.start()
    log.info("started with {} job(s)", len(scheduler.get_jobs()))
    return scheduler


def stop_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
        log.info("stopped")
    if bot_loop.running:
        from app.bots.market import market_bot

        try:
            bot_loop.run(market_bot.close(), timeout=10)
        except Exception:  # noqa: BLE001
            pass
        bot_loop.stop()


def scheduler_status() -> dict[str, Any]:
    """Snapshot for /api/health."""
    return {
        "running": scheduler.running,
        "jobs": [
            {"id": job.id, "next_run_time": job.next_run_time.replace(tzinfo=None) if job.next_run_time else None}
            for job in scheduler.get_jobs()
        ],
    }
