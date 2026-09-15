"""GET /api/health - liveness + a few freshness indicators for monitoring."""

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app import __version__
from app.auth import auth_status
from app.bots.aviation import aviation_bot
from app.bots.blockchain import blockchain_bot
from app.bots.infra import infra_bot
from app.bots.leaks import leaks_bot
from app.bots.legal import legal_bot
from app.bots.narratives import narrative_bot
from app.bots.psc import psc_bot
from app.bots.watchlist import watchlist_bot
from app.bots.corporate import corporate_bot
from app.bots.correlation import correlation_engine
from app.bots.energy import energy_bot
from app.bots.geopolitical import geopolitical_bot
from app.bots.maritime import maritime_bot
from app.bots.market import market_bot
from app.bots.sanctions import sanctions_bot
from app.bots.scheduler import scheduler_status
from app.config import settings
from app.database import DATABASE_PATH, engine, get_db
from app.models.maritime import VesselPosition
from app.models.market import MarketCandle
from app.schemas.common import DatabaseHealth, HealthResponse, SchedulerHealth
from app.utils.time import utcnow

router = APIRouter(tags=["health"])

STARTED_AT = utcnow()


def _database_size() -> int | None:
    """Size of the SQLite file including its WAL side-file, if any."""
    if DATABASE_PATH is None or not DATABASE_PATH.exists():
        return None
    size = DATABASE_PATH.stat().st_size
    wal = DATABASE_PATH.with_name(DATABASE_PATH.name + "-wal")
    if wal.exists():
        size += wal.stat().st_size
    return size


@router.get(
    "/health",
    response_model=HealthResponse,
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"description": "Database unreachable"}},
)
def health(response: Response, db: Session = Depends(get_db)) -> HealthResponse:
    """Service status.  Returns 503 (with the same body) when the database is unreachable."""
    db_ok, db_error = True, None
    last_market_update = last_ais_update = None
    try:
        db.execute(text("SELECT 1"))
        last_market_update = db.execute(select(func.max(MarketCandle.timestamp))).scalar()
        last_ais_update = db.execute(select(func.max(VesselPosition.timestamp))).scalar()
    except Exception as exc:  # noqa: BLE001 - any failure means "degraded"
        db_ok, db_error = False, str(exc)
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    now = utcnow()
    return HealthResponse(
        status="ok" if db_ok else "degraded",
        version=__version__,
        environment=settings.ENVIRONMENT,
        timestamp=now,
        uptime_seconds=round((now - STARTED_AT).total_seconds(), 1),
        database=DatabaseHealth(ok=db_ok, dialect=engine.dialect.name, size_bytes=_database_size(), error=db_error),
        scheduler=SchedulerHealth(enabled=settings.SCHEDULER_ENABLED, **scheduler_status()),
        last_market_update=last_market_update,
        last_ais_update=last_ais_update,
        bots={"market": market_bot.status(), "maritime": maritime_bot.status(), "sanctions": {k: sanctions_bot.status()[k] for k in ("active_listings", "index_size", "refreshing")}, "geopolitical": geopolitical_bot.status(), "blockchain": blockchain_bot.status(), "corporate": corporate_bot.status(), "energy": energy_bot.status(), "fusion": correlation_engine.status(), "aviation": aviation_bot.status(), "leaks": leaks_bot.status(), "infra": infra_bot.status(), "legal": legal_bot.status(), "narratives": narrative_bot.status(), "psc": psc_bot.status(), "watchlist": watchlist_bot.status(), "auth": auth_status()} if db_ok else {"auth": auth_status()},
    )
