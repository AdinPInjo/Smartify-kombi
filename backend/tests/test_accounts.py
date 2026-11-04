"""First-run setup, hashed passwords and changing the login."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from smartify.config import Settings
from smartify.main import create_app
from smartify.services.accounts import check_password, hash_password

PASSWORD = "test-password"  # as in conftest.py


@pytest.fixture
def fresh(tmp_path):
    """A new van: real-hardware rules, no password anywhere."""
    settings = Settings(
        _env_file=None,
        hardware="mock",
        data_dir=tmp_path,
        password="",
        secret_key="test-secret",
        weather_enabled=False,
    )
    with TestClient(create_app(settings, start_workers=False)) as client:
        yield client


def code_of(client) -> str:
    """The setup code, as install.sh prints it (only someone at the Pi can read it)."""
    return client.app.state.accounts.setup_code()


def test_password_hashing():
    stored = hash_password("correct horse")
    assert stored.startswith("scrypt$") and "correct horse" not in stored
    assert check_password("correct horse", stored)
    assert not check_password("wrong horse", stored)
    assert hash_password("correct horse") != stored  # salted


def test_first_run_setup(fresh):
    assert fresh.get("/api/health").json()["setup_required"] is True
    assert fresh.get("/api/setup").json() == {"required": True}
    # Nothing else works before the setup, and there is no login to try.
    response = fresh.get("/api/relays")
    assert response.status_code == 401 and response.json()["detail"] == "setup required"
    assert (
        fresh.post("/api/auth/login", json={"username": "admin", "password": "x"}).status_code
        == 409
    )

    weak = fresh.post("/api/setup", json={"username": "admin", "password": "short"})
    assert weak.status_code == 422 and "at least 8" in weak.json()["detail"]
    common = fresh.post("/api/setup", json={"username": "admin", "password": "changeme"})
    assert common.status_code == 422

    # Without the setup code, nobody else on the WiFi can create the login.
    stolen = fresh.post("/api/setup", json={"username": "evil", "password": "kombi-on-tour"})
    assert stolen.status_code == 422 and "setup code" in stolen.json()["detail"]
    created = fresh.post(
        "/api/setup",
        json={"username": "van", "password": "kombi-on-tour", "setup_code": code_of(fresh).lower()},
    )
    assert created.status_code == 201
    assert code_of(fresh) is None  # used up
    assert fresh.get("/api/relays").status_code == 200  # signed in right away
    assert fresh.get("/api/auth/me").json()["login_source"] == "dashboard"
    assert fresh.get("/api/health").json()["setup_required"] is False

    # Setup cannot be repeated to take over the van.
    again = fresh.post("/api/setup", json={"username": "evil", "password": "takeover-123"})
    assert again.status_code == 409

    fresh.post("/api/auth/logout")
    bad = fresh.post("/api/auth/login", json={"username": "van", "password": "nope-nope"})
    assert bad.status_code == 401
    good = fresh.post("/api/auth/login", json={"username": "van", "password": "kombi-on-tour"})
    assert good.status_code == 200


def test_changing_the_password_signs_out_other_devices(fresh):
    fresh.post(
        "/api/setup",
        json={"username": "admin", "password": "kombi-on-tour", "setup_code": code_of(fresh)},
    )
    other = TestClient(fresh.app)
    assert (
        other.post(
            "/api/auth/login", json={"username": "admin", "password": "kombi-on-tour"}
        ).status_code
        == 200
    )

    wrong = fresh.post(
        "/api/auth/password", json={"current_password": "nope", "new_password": "new-secret-1"}
    )
    assert wrong.status_code == 422 and "current password" in wrong.json()["detail"]
    changed = fresh.post(
        "/api/auth/password",
        json={"current_password": "kombi-on-tour", "new_password": "new-secret-1"},
    )
    assert changed.status_code == 200
    assert fresh.get("/api/relays").status_code == 200  # this device stays signed in
    assert other.get("/api/relays").status_code == 401  # the other one is signed out


def test_env_password_keeps_working_and_moves_to_the_database(client):
    me = client.get("/api/auth/me").json()
    assert me["login_source"] == "env"
    client.post(
        "/api/auth/password",
        json={
            "current_password": PASSWORD,
            "new_password": "from-the-dashboard",
            "username": "adin",
        },
    )
    assert client.get("/api/auth/me").json() == {
        "user": "adin",
        "default_credentials": False,
        "login_source": "dashboard",
    }
    client.post("/api/auth/logout")
    old = client.post("/api/auth/login", json={"username": "admin", "password": PASSWORD})
    assert old.status_code == 401
    new = client.post(
        "/api/auth/login", json={"username": "adin", "password": "from-the-dashboard"}
    )
    assert new.status_code == 200


def test_default_password_never_protects_real_hardware(tmp_path):
    settings = Settings(_env_file=None, hardware="pi", data_dir=tmp_path, secret_key="s")
    from smartify.db import migrate
    from smartify.services.accounts import AccountService

    migrate(tmp_path / "x.db")
    assert AccountService(settings, tmp_path / "x.db", "s").source == "setup"


def test_setup_code_is_kept_private_and_reused(fresh, tmp_path):
    code = code_of(fresh)
    assert code and len(code) == 9 and code[4] == "-"
    stored = tmp_path / "setup-code.txt"
    assert stored.read_text().strip() == code
    assert stored.stat().st_mode & 0o777 == 0o600
    assert code_of(fresh) == code  # the same until it's used


def test_guessing_is_stopped(fresh):
    for _ in range(5):
        wrong = fresh.post(
            "/api/setup",
            json={"username": "x", "password": "kombi-on-tour", "setup_code": "AAAA-AAAA"},
        )
        assert wrong.status_code == 422
    blocked = fresh.post(
        "/api/setup",
        json={"username": "x", "password": "kombi-on-tour", "setup_code": code_of(fresh)},
    )
    assert blocked.status_code == 429 and "try again" in blocked.json()["detail"]


def test_login_lockout_after_five_wrong_passwords(client):
    client.post("/api/auth/logout")
    for _ in range(5):
        assert (
            client.post(
                "/api/auth/login", json={"username": "admin", "password": "nope"}
            ).status_code
            == 401
        )
    locked = client.post("/api/auth/login", json={"username": "admin", "password": PASSWORD})
    assert locked.status_code == 429 and locked.headers["retry-after"]


def test_guard_window_and_overall_limit():
    from smartify.services.accounts import LoginGuard, TooManyAttempts

    now = [1000.0]
    guard = LoginGuard(clock=lambda: now[0])
    for i in range(30):
        guard.failed(f"10.0.0.{i}")
    with pytest.raises(TooManyAttempts):
        guard.check("10.0.0.99")  # many addresses together: everyone waits
    now[0] += 16 * 60
    guard.check("10.0.0.99")  # the window has passed
