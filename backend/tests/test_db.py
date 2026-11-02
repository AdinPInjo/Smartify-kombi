import sqlite3

import pytest

from smartify.db import connect, current_version, migrate, transaction
from smartify.db.migrations import load_migrations

INSERT_RELAY = (
    "INSERT INTO relays (id, name, gpio_pin, created_at, updated_at) "
    "VALUES ('r1', 'heater', 25, 0, 0)"
)


def test_migrate_creates_schema_and_is_idempotent(tmp_path):
    db_path = tmp_path / "test.db"
    latest = len(load_migrations())

    assert migrate(db_path) == latest
    assert migrate(db_path) == latest  # second run is a no-op

    conn = connect(db_path)
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {
        "relays",
        "relay_state",
        "rules",
        "sensor_samples",
        "water_level_settings",
        "gps_fixes",
        "weather_samples",
    } <= tables
    assert current_version(conn) == latest
    conn.close()


def test_water_level_settings_has_single_default_row(tmp_path):
    db_path = tmp_path / "test.db"
    migrate(db_path)
    with transaction(db_path) as conn:
        rows = conn.execute(
            "SELECT method, signal_channel, supply_channel FROM water_level_settings"
        ).fetchall()
        assert [tuple(r) for r in rows] == [("voltage", 0, 1)]
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO water_level_settings (id, updated_at) VALUES (2, 0)")


def test_foreign_keys_cascade(tmp_path):
    db_path = tmp_path / "test.db"
    migrate(db_path)
    with transaction(db_path) as conn:
        conn.execute(INSERT_RELAY)
        conn.execute("INSERT INTO relay_state (relay_id, changed_at) VALUES ('r1', 0)")
        conn.execute("DELETE FROM relays WHERE id = 'r1'")
        assert conn.execute("SELECT COUNT(*) FROM relay_state").fetchone()[0] == 0


def test_transaction_rolls_back_on_error(tmp_path):
    db_path = tmp_path / "test.db"
    migrate(db_path)
    with pytest.raises(RuntimeError), transaction(db_path) as conn:
        conn.execute(INSERT_RELAY)
        raise RuntimeError("boom")
    with transaction(db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM relays").fetchone()[0] == 0
