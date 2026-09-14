"""FastAPI application factory for VELES.

Startup: apply migrations (creates the SQLite DB on first run), then start the
bot scheduler.  Shutdown: stop the scheduler.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app import __version__
from app.api import admin, health, maritime, market, sanctions
from app.bots.scheduler import start_scheduler, stop_scheduler
from app.config import BACKEND_DIR, settings
from app.database import DATABASE_URL, init_db
from app.utils.logger import logger


@asynccontextmanager
async def lifespan(_app: FastAPI):
    logger.info("VELES {} starting ({}) - database {}", __version__, settings.ENVIRONMENT, DATABASE_URL.render_as_string(hide_password=True))
    init_db()
    if settings.SCHEDULER_ENABLED:
        start_scheduler()
    else:
        logger.warning("Scheduler disabled (SCHEDULER_ENABLED=false) - bots will not run")
    yield
    stop_scheduler()
    logger.info("VELES stopped")


app = FastAPI(
    title="VELES",
    version=__version__,
    description="OSINT intelligence platform: multi-exchange market surveillance and maritime sanctions monitoring.",
    lifespan=lifespan,
)

# The frontend is served by Vite (dev) or Nginx (prod) on a different origin
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router, prefix="/api")
app.include_router(market.router, prefix="/api/market")
app.include_router(maritime.router, prefix="/api/maritime")
app.include_router(sanctions.router, prefix="/api/sanctions")
app.include_router(admin.router, prefix="/api/admin")

# ---------------------------------------------------------------------------
# Frontend hosting.  In production Nginx serves frontend/dist directly, but the
# API can do it too so a single process gives a working UI (dev boxes, or a Pi
# without Nginx).  Registered last so API routes always win.
# ---------------------------------------------------------------------------
FRONTEND_DIST = BACKEND_DIR.parent / "frontend" / "dist"

app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets", check_dir=False), name="assets")


@app.get("/{full_path:path}", include_in_schema=False)
async def serve_frontend(full_path: str):
    """Serve the built single-page app with history-API fallback."""
    if full_path.startswith("api/"):
        raise HTTPException(status_code=404, detail="Not found")
    index = FRONTEND_DIST / "index.html"
    if not index.is_file():
        return JSONResponse(
            {"message": "VELES API is running; the frontend has not been built.", "docs": "/docs", "health": "/api/health"}
        )
    candidate = FRONTEND_DIST / full_path
    if full_path and candidate.is_file() and candidate.resolve().is_relative_to(FRONTEND_DIST.resolve()):
        return FileResponse(candidate)
    return FileResponse(index)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=settings.API_HOST, port=settings.API_PORT)
