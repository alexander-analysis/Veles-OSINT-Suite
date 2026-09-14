"""Application settings.

Values come from environment variables, falling back to ``backend/.env``
(see ``.env.example``).  Secrets (exchange / MarineTraffic keys) live here and
are never exposed through the API.  Tunable thresholds and cadences live in
``settings.yaml`` and are managed through ``/api/admin/config`` instead.
"""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/ - every relative path in the settings is resolved against this, so
# the service behaves the same whether it is started from backend/, the repo
# root, or systemd.
BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    DATABASE_URL: str = "sqlite:///./veles.db"
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8000
    ENVIRONMENT: str = "development"
    LOG_LEVEL: str = "INFO"
    CORS_ORIGINS: str = "*"
    SCHEDULER_ENABLED: bool = True

    # Non-secret tunables (thresholds, cadences) - see settings.yaml
    SETTINGS_FILE: str = "settings.yaml"
    SETTINGS_OVERRIDES_FILE: str = "settings.local.yaml"

    # Exchange APIs
    BINANCE_API_KEY: str = ""
    KRAKEN_API_KEY: str = ""
    COINBASE_API_KEY: str = ""

    # Maritime APIs
    MARINETRAFFIC_API_KEY: str = ""

    # Cloudflare Tunnel
    CLOUDFLARE_TOKEN: str = ""

    def resolve_path(self, value: str | Path) -> Path:
        """Return ``value`` as an absolute path, anchored at backend/ if relative."""
        path = Path(value)
        return path if path.is_absolute() else (BACKEND_DIR / path).resolve()

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]


settings = Settings()
