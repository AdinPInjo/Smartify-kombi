from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from smartify.config import Settings
from smartify.main import create_app


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        hardware="mock",
        data_dir=tmp_path,
        password="test-password",
        secret_key="test-secret",
    )


@pytest.fixture
def client(settings: Settings):
    with TestClient(create_app(settings)) as test_client:
        yield test_client
