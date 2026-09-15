"""Alert delivery: Slack-compatible webhook and SMTP e-mail (instant alerts + daily digest).

Configuration: ``notifications`` section in ``settings.yaml`` (enabled,
minimum severity, recipients, digest hour) and credentials in ``.env``
(``NOTIFY_WEBHOOK_URL``, ``SMTP_*``).  Delivery is fire-and-forget from the
bot loop and never raises into the caller - a broken mail server must not
stop detection.
"""

import asyncio
import smtplib
from datetime import timedelta
from email.message import EmailMessage
from typing import Any

import httpx

from app.config import settings
from app.utils import config_store
from app.utils.logger import logger

log = logger.bind(component="notify")

SEVERITY_RANK = {"low": 0, "medium": 1, "high": 2, "critical": 3}


def _config() -> dict[str, Any]:
    return config_store.get_config().get("notifications", {})


def enabled_channels() -> dict[str, bool]:
    cfg = _config()
    return {
        "webhook": bool(cfg.get("enabled") and cfg.get("webhook_enabled", True) and settings.key("NOTIFY_WEBHOOK_URL")),
        "email": bool(cfg.get("enabled") and cfg.get("email_enabled", True) and settings.key("SMTP_HOST") and cfg.get("email_to")),
    }


async def _post_webhook(text: str, data: dict[str, Any] | None) -> None:
    url = settings.key("NOTIFY_WEBHOOK_URL")
    payload = {"text": text}
    if data:
        payload["attachments"] = [{"text": "\n".join(f"{k}: {v}" for k, v in data.items() if v is not None)}]
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.post(url, json=payload)
        response.raise_for_status()


def _send_email(subject: str, body: str, recipients: list[str]) -> None:
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = settings.key("SMTP_FROM") or settings.key("SMTP_USER") or "veles@localhost"
    message["To"] = ", ".join(recipients)
    message.set_content(body)
    host, port = settings.key("SMTP_HOST"), settings.SMTP_PORT
    if port == 465:
        server = smtplib.SMTP_SSL(host, port, timeout=20)
    else:
        server = smtplib.SMTP(host, port, timeout=20)
        server.starttls()
    with server:
        if settings.key("SMTP_USER"):
            server.login(settings.key("SMTP_USER"), settings.key("SMTP_PASSWORD"))
        server.send_message(message)


async def deliver(subject: str, text: str, data: dict[str, Any] | None = None) -> dict[str, str]:
    """Send through every enabled channel; returns per-channel outcome."""
    channels = enabled_channels()
    outcome: dict[str, str] = {}
    if channels["webhook"]:
        try:
            await _post_webhook(f"*{subject}*\n{text}", data)
            outcome["webhook"] = "sent"
        except Exception as exc:  # noqa: BLE001
            outcome["webhook"] = f"failed: {exc}"
            log.warning("webhook delivery failed: {}", exc)
    if channels["email"]:
        try:
            await asyncio.to_thread(_send_email, subject, text + ("\n\n" + "\n".join(f"{k}: {v}" for k, v in (data or {}).items()) if data else ""), list(_config().get("email_to", [])))
            outcome["email"] = "sent"
        except Exception as exc:  # noqa: BLE001
            outcome["email"] = f"failed: {exc}"
            log.warning("email delivery failed: {}", exc)
    return outcome


def send_alert(kind: str, title: str, text: str, severity: str = "high", data: dict[str, Any] | None = None) -> None:
    """Fire-and-forget instant alert (call from the bot loop or any thread)."""
    cfg = _config()
    if not cfg.get("enabled"):
        return
    if SEVERITY_RANK.get(severity, 0) < SEVERITY_RANK.get(cfg.get("min_severity", "high"), 2):
        return
    if not any(enabled_channels().values()):
        return
    subject = f"[VELES {severity.upper()}] {title}"
    try:
        from app.bots.runtime import bot_loop

        bot_loop.submit(deliver(subject, text, {"kind": kind, **(data or {})}))
    except Exception as exc:  # noqa: BLE001
        log.warning("could not schedule alert: {}", exc)


def build_daily_digest() -> tuple[str, str]:
    """Summarise the last 24 hours across all bots."""
    from sqlalchemy import func, select

    from app.database import SessionLocal
    from app.models.maritime import EvasionEvent, PortCallEvent, SanctionsBreach, TransshipmentEvent, Vessel
    from app.models.market import MarketAlert
    from app.models.sanctions import SanctionsUpdate
    from app.utils.time import utcnow

    since = utcnow() - timedelta(hours=24)
    with SessionLocal() as db:
        breaches = db.execute(select(SanctionsBreach).where(SanctionsBreach.timestamp >= since).order_by(SanctionsBreach.match_confidence.desc())).scalars().all()
        evasion = db.execute(select(EvasionEvent.event_type, func.count()).where(EvasionEvent.timestamp >= since).group_by(EvasionEvent.event_type)).all()
        sts = db.execute(select(func.count(TransshipmentEvent.id)).where(TransshipmentEvent.timestamp >= since)).scalar() or 0
        calls = db.execute(select(func.count(PortCallEvent.id)).where(PortCallEvent.arrival_time >= since, PortCallEvent.is_sanctioned_facility.is_(True))).scalar() or 0
        alerts = db.execute(select(MarketAlert.severity, func.count()).where(MarketAlert.timestamp >= since).group_by(MarketAlert.severity)).all()
        updates = db.execute(select(SanctionsUpdate.authority, SanctionsUpdate.update_type, func.count()).where(SanctionsUpdate.timestamp >= since).group_by(SanctionsUpdate.authority, SanctionsUpdate.update_type)).all()
        tracked = db.execute(select(func.count(Vessel.id)).where(Vessel.last_ais_update >= since)).scalar() or 0
    lines = [
        f"VELES daily digest - {utcnow():%Y-%m-%d %H:%M} UTC",
        "",
        f"Maritime: {tracked:,} vessels active; {len(breaches)} new sanctions match(es); {sts} STS candidate(s); {calls} call(s) at sanctioned facilities.",
    ]
    for b in breaches[:15]:
        lines.append(f"  - {b.sanctioning_authority} {b.vessel_name} ({b.flag}) -> {b.sanctioned_entity_name} [{b.breach_type}, {b.match_confidence:.2f}]")
    if evasion:
        lines.append("Evasion indicators: " + ", ".join(f"{k}: {n}" for k, n in evasion))
    lines.append("Market alerts: " + (", ".join(f"{k}: {n}" for k, n in alerts) or "none"))
    lines.append("Sanctions list changes: " + (", ".join(f"{a} {t}: {n}" for a, t, n in updates) or "none"))
    try:
        from app.bots.correlation import correlation_engine

        with SessionLocal() as db:
            fusion = correlation_engine.summary(db, 24)
        lines.append(f"Fusion: {fusion['composite_alerts']} composite alert(s) ({fusion['critical_open']} critical open), {fusion['correlations']} cross-domain links.")
        for alert in fusion.get("top_alerts", [])[:5]:
            lines.append(f"  - [{alert['severity']}] {alert['title']} ({alert['signals']} signals, {', '.join(alert['domains'])})")
    except Exception as exc:  # noqa: BLE001 - the digest must go out even if fusion is unavailable
        lines.append(f"Fusion summary unavailable: {exc}")
    return f"[VELES] Daily intelligence digest {utcnow():%Y-%m-%d}", "\n".join(lines)


async def send_daily_digest() -> dict[str, str]:
    if not _config().get("enabled") or not _config().get("digest_enabled", True):
        return {}
    subject, body = build_daily_digest()
    outcome = await deliver(subject, body)
    log.info("daily digest: {}", outcome or "no channels configured")
    return outcome
