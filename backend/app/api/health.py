"""GET /api/health - liveness + a few freshness indicators for monitoring."""

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app import __version__
from app.bots.market import market_bot
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
        bots={"market": market_bot.status()} if db_ok else {},
    )
