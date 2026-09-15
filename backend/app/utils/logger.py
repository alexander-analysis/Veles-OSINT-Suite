"""Loguru configuration.

Console output goes to stderr (WARNING and above in production, since the
Pi's systemd unit appends it to an unrotated file); files rotate under
``backend/logs/``:

* ``veles.log``  - everything at LOG_LEVEL and above
* ``errors.log`` - ERROR and above only
* ``bots.log``   - only lines from the market/maritime bots and the scheduler

Bots bind a ``component`` so their lines are easy to grep:
``logger.bind(component="market")``.
"""

import sys

from loguru import logger

from app.config import BACKEND_DIR, settings

LOG_DIR = BACKEND_DIR / "logs"
BOT_COMPONENTS = {"market", "maritime", "scheduler"}

_FORMAT = (
    "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | "
    "<cyan>{extra[component]}</cyan> | {message}"
)


def configure_logging() -> None:
    LOG_DIR.mkdir(exist_ok=True)
    logger.remove()
    logger.configure(extra={"component": "app"})
    # In production the rotated files carry the full log; the unrotated stderr capture (systemd append) only gets warnings
    logger.add(sys.stderr, level="WARNING" if settings.ENVIRONMENT == "production" else settings.LOG_LEVEL, format=_FORMAT)
    logger.add(
        LOG_DIR / "veles.log",
        level=settings.LOG_LEVEL,
        format=_FORMAT,
        rotation="10 MB",
        retention="30 days",
        compression="zip",
        enqueue=True,
    )
    logger.add(
        LOG_DIR / "bots.log",
        level=settings.LOG_LEVEL,
        format=_FORMAT,
        filter=lambda record: record["extra"].get("component") in BOT_COMPONENTS,
        rotation="10 MB",
        retention="30 days",
        compression="zip",
        enqueue=True,
    )
    logger.add(
        LOG_DIR / "errors.log",
        level="ERROR",
        format=_FORMAT,
        rotation="10 MB",
        retention="30 days",
        compression="zip",
        enqueue=True,
    )


configure_logging()

__all__ = ["logger", "configure_logging", "LOG_DIR"]
