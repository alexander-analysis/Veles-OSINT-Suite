"""APScheduler wiring for the perpetual bots.

Bot coroutines run on the dedicated bot event loop (``app.bots.runtime``);
APScheduler worker threads only submit them and wait.  Job defaults are tuned
for a Pi: a slow run is never overlapped by the next one (``max_instances=1``)
and missed runs collapse into one (``coalesce``).

Cadences are read from ``settings.yaml`` when the scheduler starts; thresholds
are re-read by the bots on every run.
"""

from datetime import datetime, timedelta, timezone
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


def register_maritime_jobs() -> None:
    from app.bots.maritime import maritime_bot

    cfg = config_store.get_config()
    maritime = cfg.get("maritime", {})
    sanctions = cfg.get("sanctions", {})
    retention = cfg.get("retention", {})
    scheduler.add_job(_on_loop(maritime_bot.fetch_ais_positions, timeout=120), "interval", seconds=int(maritime.get("ais_poll_interval_seconds", 30)), id="maritime.fetch_ais", replace_existing=True)
    # First screening pass ~2 minutes after boot (the list import/index build takes ~20 s), then every N minutes
    scheduler.add_job(
        _on_loop(maritime_bot.check_sanctions, timeout=600),
        "interval",
        minutes=int(maritime.get("sanctions_check_interval_minutes", 15)),
        next_run_time=datetime.now(timezone.utc) + timedelta(seconds=120),
        id="maritime.check_sanctions",
        replace_existing=True,
    )
    scheduler.add_job(_on_loop(maritime_bot.detect_transshipments, timeout=300), "interval", minutes=5, id="maritime.detect_transshipments", replace_existing=True)
    scheduler.add_job(_on_loop(maritime_bot.detect_port_calls, timeout=300), "interval", minutes=5, id="maritime.detect_port_calls", replace_existing=True)
    scheduler.add_job(_on_loop(maritime_bot.detect_dark_vessels, timeout=300), "interval", minutes=15, id="maritime.detect_dark_vessels", replace_existing=True)
    scheduler.add_job(_on_loop(maritime_bot.update_risk_scores, timeout=600), "interval", minutes=int(sanctions.get("check_maritime_interval_minutes", 30)), id="maritime.update_risk_scores", replace_existing=True)
    scheduler.add_job(_on_loop(maritime_bot.cleanup_old_data, timeout=1800), "cron", hour=int(retention.get("purge_hour_utc", 2)), minute=30, id="maritime.cleanup_old_data", replace_existing=True)
    scheduler.add_job(_on_loop(maritime_bot.fetch_ais_positions, timeout=120), id="maritime.initial_fetch", replace_existing=True)


def register_geopolitical_jobs() -> None:
    from app.bots.geopolitical import geopolitical_bot

    cfg = config_store.get_config()
    geo = cfg.get("geopolitical", {})
    retention = cfg.get("retention", {})
    if not geo.get("enabled", True):
        log.info("geopolitical monitor disabled in settings")
        return
    boot = datetime.now(timezone.utc)
    scheduler.add_job(_on_loop(geopolitical_bot.fetch_gdelt_events, timeout=300), "interval", minutes=int(geo.get("gdelt_events_interval_minutes", 15)),
                      next_run_time=boot + timedelta(seconds=45), id="geopolitical.gdelt_events", replace_existing=True)
    scheduler.add_job(_on_loop(geopolitical_bot.fetch_topic_articles, timeout=600), "interval", minutes=int(geo.get("doc_interval_minutes", 30)),
                      next_run_time=boot + timedelta(seconds=150), id="geopolitical.gdelt_doc", replace_existing=True)
    scheduler.add_job(_on_loop(geopolitical_bot.fetch_official_feeds, timeout=300), "interval", minutes=int(geo.get("official_feeds_interval_minutes", 30)),
                      next_run_time=boot + timedelta(seconds=90), id="geopolitical.official_feeds", replace_existing=True)
    scheduler.add_job(_on_loop(geopolitical_bot.correlate, timeout=300), "interval", minutes=int(geo.get("correlation_interval_minutes", 10)),
                      next_run_time=boot + timedelta(seconds=300), id="geopolitical.correlate", replace_existing=True)
    scheduler.add_job(_on_loop(geopolitical_bot.cleanup_old_data, timeout=600), "cron", hour=int(retention.get("purge_hour_utc", 2)), minute=45,
                      id="geopolitical.cleanup_old_data", replace_existing=True)


def register_blockchain_jobs() -> None:
    from app.bots.blockchain import blockchain_bot

    cfg = config_store.get_config()
    chain = cfg.get("blockchain", {})
    retention = cfg.get("retention", {})
    if not chain.get("enabled", True):
        log.info("blockchain tracker disabled in settings")
        return
    boot = datetime.now(timezone.utc)
    # Wallet sync needs the sanctions lists: first pass ~3 minutes after boot, then hourly
    scheduler.add_job(_on_loop(blockchain_bot.sync_sanctioned_wallets, timeout=300), "interval", hours=1, next_run_time=boot + timedelta(seconds=180), id="blockchain.sync_wallets", replace_existing=True)
    scheduler.add_job(_on_loop(blockchain_bot.refresh_prices, timeout=60), "interval", minutes=10, next_run_time=boot + timedelta(seconds=60), id="blockchain.prices", replace_existing=True)
    scheduler.add_job(_on_loop(blockchain_bot.poll_wallets, timeout=600), "interval", minutes=int(chain.get("poll_interval_minutes", 10)), next_run_time=boot + timedelta(seconds=240), id="blockchain.poll_wallets", replace_existing=True)
    scheduler.add_job(_on_loop(blockchain_bot.scan_ethereum, timeout=240), "interval", seconds=int(chain.get("ethereum_scan_interval_seconds", 180)), next_run_time=boot + timedelta(seconds=210), id="blockchain.scan_ethereum", replace_existing=True)
    scheduler.add_job(_on_loop(blockchain_bot.flush_stream, timeout=120), "interval", seconds=30, id="blockchain.flush_stream", replace_existing=True)
    scheduler.add_job(_on_loop(blockchain_bot.cleanup_old_data, timeout=600), "cron", hour=int(retention.get("purge_hour_utc", 2)), minute=50, id="blockchain.cleanup_old_data", replace_existing=True)
    if chain.get("bitcoin_stream_enabled", True):
        bot_loop.run(_start_bitcoin_stream())


async def _start_bitcoin_stream() -> None:
    from app.bots.blockchain import blockchain_bot

    blockchain_bot.ensure_stream()


def register_corporate_jobs() -> None:
    from app.bots.corporate import corporate_bot

    cfg = config_store.get_config().get("corporate", {})
    if not cfg.get("enabled", True):
        log.info("corporate intelligence disabled in settings")
        return
    boot = datetime.now(timezone.utc)
    # Seed from the sanctions lists once they are loaded (~4 min after boot), then daily
    scheduler.add_job(_on_loop(corporate_bot.seed_companies, timeout=600), "interval", hours=24, next_run_time=boot + timedelta(seconds=240), id="corporate.seed", replace_existing=True)
    scheduler.add_job(_on_loop(corporate_bot.enrich_companies, timeout=900), "interval", minutes=int(cfg.get("enrich_interval_minutes", 10)), next_run_time=boot + timedelta(seconds=360),
                      id="corporate.enrich", replace_existing=True)


def register_energy_jobs() -> None:
    from app.bots.energy import energy_bot

    cfg = config_store.get_config().get("energy", {})
    if not cfg.get("enabled", True):
        log.info("energy monitor disabled in settings")
        return
    boot = datetime.now(timezone.utc)
    scheduler.add_job(_on_loop(energy_bot.sync_facilities, timeout=300), "interval", hours=12, next_run_time=boot + timedelta(seconds=150), id="energy.sync_facilities", replace_existing=True)
    scheduler.add_job(_on_loop(energy_bot.track_facility_visits, timeout=300), "interval", minutes=int(cfg.get("visit_interval_minutes", 5)), next_run_time=boot + timedelta(seconds=200),
                      id="energy.track_visits", replace_existing=True)
    scheduler.add_job(_on_loop(energy_bot.build_shipments, timeout=300), "interval", minutes=int(cfg.get("shipment_interval_minutes", 15)), next_run_time=boot + timedelta(seconds=260),
                      id="energy.build_shipments", replace_existing=True)
    scheduler.add_job(_on_loop(energy_bot.detect_dark_oil, timeout=300), "interval", minutes=int(cfg.get("dark_oil_interval_minutes", 15)), next_run_time=boot + timedelta(seconds=320),
                      id="energy.detect_dark_oil", replace_existing=True)
    scheduler.add_job(_on_loop(energy_bot.snapshot_flows, timeout=300), "interval", minutes=int(cfg.get("snapshot_interval_minutes", 60)), next_run_time=boot + timedelta(seconds=380),
                      id="energy.snapshot_flows", replace_existing=True)


def register_correlation_jobs() -> None:
    from app.bots.correlation import correlation_engine

    cfg = config_store.get_config().get("correlation", {})
    if not cfg.get("enabled", True):
        log.info("correlation engine disabled in settings")
        return
    scheduler.add_job(_on_loop(correlation_engine.run, timeout=300), "interval", minutes=int(cfg.get("interval_minutes", 5)),
                      next_run_time=datetime.now(timezone.utc) + timedelta(seconds=420), id="fusion.correlate", replace_existing=True)


def register_notification_jobs() -> None:
    from app import notifications

    cfg = config_store.get_config().get("notifications", {})
    scheduler.add_job(_on_loop(notifications.send_daily_digest, timeout=120), "cron", hour=int(cfg.get("digest_hour_utc", 7)), minute=0, id="notifications.daily_digest", replace_existing=True)


def start_scheduler() -> BackgroundScheduler:
    """Register the standing jobs and start the scheduler (idempotent)."""
    if scheduler.running:
        return scheduler
    bot_loop.start()
    scheduler.add_job(_heartbeat, "interval", minutes=5, id="heartbeat", replace_existing=True)
    register_market_jobs()
    register_sanctions_jobs()
    register_maritime_jobs()
    register_geopolitical_jobs()
    register_blockchain_jobs()
    register_corporate_jobs()
    register_energy_jobs()
    register_correlation_jobs()
    register_notification_jobs()
    scheduler.start()
    log.info("started with {} job(s)", len(scheduler.get_jobs()))
    return scheduler


def stop_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
        log.info("stopped")
    if bot_loop.running:
        from app.bots.blockchain import blockchain_bot
        from app.bots.maritime import maritime_bot
        from app.bots.market import market_bot

        if blockchain_bot.stream:
            blockchain_bot.stream.stop()
        for bot in (market_bot, maritime_bot):
            try:
                bot_loop.run(bot.close(), timeout=10)
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
