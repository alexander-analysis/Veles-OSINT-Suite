"""Test configuration.

Environment variables are set *before* ``app`` is imported so the settings
object picks up a throw-away SQLite database and the scheduler stays off.
"""

import os
import tempfile
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="veles-test-"))
os.environ["DATABASE_URL"] = f"sqlite:///{(_TMP / 'test.db').as_posix()}"
os.environ["SCHEDULER_ENABLED"] = "false"
os.environ["SETTINGS_OVERRIDES_FILE"] = str(_TMP / "settings.local.yaml")
os.environ["LOG_LEVEL"] = "WARNING"
os.environ["ENVIRONMENT"] = "test"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture(scope="session")
def client():
    """TestClient with the lifespan run (migrations applied)."""
    from app.main import app

    with TestClient(app) as test_client:
        yield test_client
