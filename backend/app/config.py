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
    AISSTREAM_API_KEY: str = ""
    AISHUB_USERNAME: str = ""
    OPENWEATHERMAP_API_KEY: str = ""
    RTL_AIS_UDP_PORT: int = 10110

    # Ecosystem bots (all optional - every source has a keyless default)
    ETHEREUM_RPC_URL: str = ""
    EDGAR_CONTACT_EMAIL: str = ""
    COMPANIES_HOUSE_API_KEY: str = ""
    OPENCORPORATES_API_TOKEN: str = ""
    ETHERSCAN_API_KEY: str = ""
    EIA_API_KEY: str = ""
    NASA_FIRMS_MAP_KEY: str = ""

    # Cloudflare Tunnel
    CLOUDFLARE_TOKEN: str = ""

    # Optional API protection (see app/auth.py)
    VELES_API_TOKEN: str = ""

    # Notifications (see app/notifications.py)
    NOTIFY_WEBHOOK_URL: str = ""
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = ""

    def resolve_path(self, value: str | Path) -> Path:
        """Return ``value`` as an absolute path, anchored at backend/ if relative."""
        path = Path(value)
        return path if path.is_absolute() else (BACKEND_DIR / path).resolve()

    def key(self, name: str) -> str:
        """Return a configured secret, treating the .env.example placeholders as unset."""
        value = getattr(self, name, "") or ""
        return "" if value.startswith("your_") else value

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]


settings = Settings()
