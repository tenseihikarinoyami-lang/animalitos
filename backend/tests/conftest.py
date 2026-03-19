from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app, scheduler
from app.services.database import db_service
from app.services.monitoring import monitoring_service
from app.services.rate_limit import rate_limiter


@pytest.fixture(autouse=True)
def reset_mock_database():
    monitoring_service._backfill_task = None
    db_service.db = None
    db_service.reset_mock_state()
    rate_limiter.reset()
    original_password = settings.bootstrap_admin_password
    original_allow_insecure = settings.allow_insecure_dev_admin
    settings.bootstrap_admin_password = "admin123"
    settings.allow_insecure_dev_admin = False
    yield
    monitoring_service._backfill_task = None
    db_service.db = None
    db_service.reset_mock_state()
    rate_limiter.reset()
    settings.bootstrap_admin_password = original_password
    settings.allow_insecure_dev_admin = original_allow_insecure


@pytest.fixture
def fixtures_dir() -> Path:
    return Path(__file__).parent / "fixtures"


@pytest.fixture
def client():
    scheduler.start = lambda *args, **kwargs: None
    scheduler.shutdown = lambda *args, **kwargs: None
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def admin_headers(client):
    response = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "admin123"},
    )
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}
