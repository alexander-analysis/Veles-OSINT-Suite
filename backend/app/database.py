"""SQLAlchemy engine, session factory, declarative base and schema bootstrap.

Conventions used across the whole schema:

* All ``DateTime`` columns hold **naive UTC** values (see ``app.utils.time``).
* SQLite runs in WAL mode so the API threads and the APScheduler bot threads
  can read while another thread writes (avoids "database is locked").
* The schema is owned by Alembic: ``init_db()`` upgrades to ``head`` on
  startup, which creates the database on first run.
"""

from pathlib import Path

from sqlalchemy import MetaData, create_engine, event
from sqlalchemy.engine import URL, make_url
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import BACKEND_DIR, settings


def _anchor_sqlite_url(url: str) -> URL:
    """Resolve a relative SQLite file path against backend/ instead of the CWD."""
    parsed = make_url(url)
    database = parsed.database
    if parsed.drivername.startswith("sqlite") and database and database != ":memory:":
        path = Path(database)
        if not path.is_absolute():
            parsed = parsed.set(database=(BACKEND_DIR / path).resolve().as_posix())
    return parsed


DATABASE_URL: URL = _anchor_sqlite_url(settings.DATABASE_URL)
IS_SQLITE = DATABASE_URL.drivername.startswith("sqlite")
# Path of the SQLite file (None for other backends or in-memory databases)
DATABASE_PATH: Path | None = (
    Path(DATABASE_URL.database)
    if IS_SQLITE and DATABASE_URL.database not in (None, ":memory:")
    else None
)

# 60 s busy timeout: several bots write from different threads and a big AIS batch can hold the lock for a while
connect_args = {"timeout": 60, "check_same_thread": False} if IS_SQLITE else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args, pool_pre_ping=True)


if IS_SQLITE:

    @event.listens_for(engine, "connect")
    def _configure_sqlite_connection(dbapi_connection, _record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine, class_=Session)


class Base(DeclarativeBase):
    """Declarative base shared by every ORM model.

    The naming convention gives every constraint a deterministic name, which
    SQLite batch migrations need in order to alter or drop them later.
    """

    metadata = MetaData(
        naming_convention={
            "ix": "ix_%(column_0_label)s",
            "uq": "uq_%(table_name)s_%(column_0_name)s",
            "ck": "ck_%(table_name)s_%(constraint_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
            "pk": "pk_%(table_name)s",
        }
    )


def get_db():
    """FastAPI dependency: one session per request, always closed."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Bring the schema to the latest Alembic revision (creates the DB on first run)."""
    from alembic import command
    from alembic.config import Config

    import app.models  # noqa: F401  - make sure every table is registered on Base

    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    # Don't let Alembic's fileConfig() replace uvicorn/loguru handlers
    config.attributes["skip_logging_config"] = True
    command.upgrade(config, "head")
