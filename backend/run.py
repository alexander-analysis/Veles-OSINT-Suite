"""Start the VELES API server.

Used by the systemd unit on the Pi and for local development:

    cd backend && python run.py
"""

if __name__ == "__main__":
    import uvicorn

    from app.config import settings
    from app.main import app

    uvicorn.run(
        app,
        host=settings.API_HOST,
        port=settings.API_PORT,
        log_level=settings.LOG_LEVEL.lower(),
    )
