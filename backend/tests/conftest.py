from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from smartify.config import Settings
from smartify.main import create_app

PASSWORD = "test-password"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        hardware="mock",
        data_dir=tmp_path,
        password=PASSWORD,
        secret_key="test-secret",
        weather_enabled=False,
    )


@pytest.fixture
def anon(settings: Settings):
    """Client that is not logged in. Background workers are not started."""
    with TestClient(create_app(settings, start_workers=False)) as test_client:
        yield test_client


@pytest.fixture
def client(anon: TestClient) -> TestClient:
    """Logged-in client."""
    response = anon.post("/api/auth/login", json={"username": "admin", "password": PASSWORD})
    assert response.status_code == 200
    return anon


@pytest.fixture
def ctx(client: TestClient):
    return client.app.state.ctx
