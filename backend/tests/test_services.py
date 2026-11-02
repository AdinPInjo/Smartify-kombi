"""Unit tests for sensor, water, GPS, weather, WiFi and housekeeping logic."""

from __future__ import annotations

import time

import pytest

from smartify.config import Settings
from smartify.db import migrate, transaction
from smartify.hardware import ClimateReading, GpsFix, HardwareError
from smartify.services.climate import ClimateService
from smartify.services.conditions import SensorIssue
from smartify.services.gps import GpsService, distance_m
from smartify.services.maintenance import prune_history
from smartify.services.water import WaterService, level_percent
from smartify.services.weather import WeatherService, build_url, parse_response
from smartify.services.wifi import parse_scan, split_terse
from smartify.workers import Worker


class Clock:
    def __init__(self) -> None:
        self.now = 1_700_000_000.0

    def __call__(self) -> float:
        return self.now


class ScriptedSensor:
    def __init__(self, name: str) -> None:
        self.name = name
        self.next: list[ClimateReading] = []

    def push(self, temperature: float | None, humidity: float | None = 50.0) -> None:
        error = None if temperature is not None else "checksum"
        self.next.append(ClimateReading(self.name, temperature, humidity, error))

    def read(self) -> ClimateReading:
        return self.next.pop(0)


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "t.db"
    migrate(path)
    return path


# --- climate -------------------------------------------------------------------


def test_climate_warms_up_averages_and_goes_stale(db):
    settings = Settings(_env_file=None, sensor_min_samples=3, sensor_stale_seconds=600)
    clock, sensor = Clock(), ScriptedSensor("inside")
    climate = ClimateService(settings, [sensor], db, clock)

    sensor.push(10.0)
    climate.sample()
    assert climate.metric("inside", "temperature").issue is SensorIssue.WARMING_UP

    for value in (11.0, 12.0):
        clock.now += 5
        sensor.push(value)
        climate.sample()
    value = climate.metric("inside", "temperature")
    assert value.issue is None and value.value == pytest.approx(11.0)

    # Failed reads keep the last average until the stale limit.
    clock.now += 300
    sensor.push(None)
    climate.sample()
    assert climate.metric("inside", "temperature").value == pytest.approx(11.0)

    clock.now += 400
    assert climate.metric("inside", "temperature").issue is SensorIssue.STALE
    assert climate.metric("nope", "temperature").issue is SensorIssue.MISSING


def test_climate_never_working_sensor_becomes_stale(db):
    settings = Settings(_env_file=None, sensor_stale_seconds=600)
    clock, sensor = Clock(), ScriptedSensor("inside")
    climate = ClimateService(settings, [sensor], db, clock)
    sensor.push(None)
    climate.sample()
    assert climate.snapshot("inside").status == "warming_up"
    clock.now += 601
    assert climate.snapshot("inside").status == "stale"


def test_climate_stores_one_row_per_minute(db):
    settings = Settings(_env_file=None)
    clock, sensor = Clock(), ScriptedSensor("inside")
    climate = ClimateService(settings, [sensor], db, clock)
    for value in (20.0, 22.0):
        sensor.push(value, 40.0)
        climate.sample()
    climate.flush_minute()
    climate.flush_minute()  # nothing new: no row
    rows = climate.history("inside", 0)
    assert len(rows) == 1 and rows[0]["temperature_c"] == pytest.approx(21.0)


# --- water -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "empty", "full", "expected"),
    [
        (0.1, 0.163, 0.037, 50),  # sender reads lower when full
        (0.037, 0.163, 0.037, 100),
        (0.5, 0.163, 0.037, 0),  # clamped
        (1.5, 1.0, 2.0, 50),  # sender reads higher when full
    ],
)
def test_level_percent(value, empty, full, expected):
    assert level_percent(value, empty, full) == expected


class FixedAnalog:
    def __init__(self, signal: float, supply_divided: float) -> None:
        self.values = (signal, supply_divided)
        self.fail = False

    def read_voltages(self, channels):
        if self.fail:
            raise HardwareError("ADS1115 not responding")
        return self.values


def test_ratio_method_cancels_battery_drift(db):
    battery_low, battery_high = 12.0, 14.4
    divider = 10 / 57
    ratio = 0.1  # same water level

    readings = []
    for battery in (battery_low, battery_high):
        water = WaterService(FixedAnalog(battery * ratio, battery * divider), db)
        water.sample()
        readings.append(water.current())
    assert readings[0].level_percent == readings[1].level_percent == 50
    assert readings[0].battery_voltage == pytest.approx(12.0)
    assert readings[1].battery_voltage == pytest.approx(14.4)


def test_water_reports_hardware_errors(db):
    analog = FixedAnalog(1.0, 2.0)
    analog.fail = True
    water = WaterService(analog, db)
    water.sample()
    reading = water.current()
    assert reading.ok is False and "not responding" in reading.error


# --- GPS -------------------------------------------------------------------------


def test_distance_m():
    # Travnik -> Sarajevo, about 70 km in a straight line
    assert distance_m(44.2264, 17.6658, 43.8563, 18.4131) == pytest.approx(71_500, rel=0.05)


def test_gps_ignores_jitter_when_parked_and_counts_driving(db):
    clock = Clock()
    gps = GpsService(receiver=None, db_path=db, clock=clock)
    lat, lon = 44.0, 17.0
    for i in range(10):  # parked with jitter
        clock.now += 1
        gps.process(GpsFix(lat + i * 1e-5, lon, speed_kmh=0.5))
    assert gps.total_distance_km() == 0
    assert len(gps.track(0)) == 1  # one heartbeat point

    for i in range(1, 11):  # drive north ~111 m per step
        clock.now += 10
        gps.process(GpsFix(lat + i * 0.001, lon, speed_kmh=40))
    assert gps.total_distance_km() == pytest.approx(1.0, rel=0.05)
    assert len(gps.track(0)) == 11


# --- weather ---------------------------------------------------------------------

OPEN_METEO = {
    "current": {
        "temperature_2m": 4.2,
        "relative_humidity_2m": 81,
        "wind_speed_10m": 12.0,
        "weather_code": 3,
    },
    "daily": {
        "time": ["2026-11-03", "2026-11-04"],
        "temperature_2m_max": [8.1, 9.0],
        "temperature_2m_min": [-1.0, 0.5],
        "precipitation_sum": [0.0, 2.4],
        "weather_code": [3, 61],
    },
}


def test_weather_parse_and_url():
    parsed = parse_response(OPEN_METEO)
    assert parsed["temperature_c"] == 4.2
    assert parsed["forecast"][1]["precipitation_mm"] == 2.4
    assert "latitude=44.2264" in build_url(44.22641, 17.6658)


def test_weather_refresh_and_backoff(db):
    clock = Clock()
    gps = GpsService(receiver=None, db_path=db, clock=clock)
    gps.process(GpsFix(44.0, 17.0, speed_kmh=0))
    calls = []

    def fetcher(url):
        calls.append(url)
        if len(calls) == 1:
            raise OSError("no internet")
        return OPEN_METEO

    weather = WeatherService(gps, db, interval_seconds=1800, fetcher=fetcher, clock=clock)
    weather.refresh_if_due()
    assert "no internet" in weather.current()["error"]
    weather.refresh_if_due()  # within back-off: no new call
    assert len(calls) == 1
    clock.now += 301
    weather.refresh_if_due()
    assert weather.current()["temperature_c"] == 4.2
    assert len(weather.history(0)) == 1


# --- WiFi ----------------------------------------------------------------------


def test_split_terse_handles_escapes():
    assert split_terse(r"*:My\:Net:70:WPA2") == ["*", "My:Net", "70", "WPA2"]


def test_parse_scan_dedupes_and_sorts():
    output = "\n".join(
        [
            " :Camping:40:",
            " :Camping:65:",
            "*:Home:55:WPA2",
            " ::80:WPA2",  # hidden network
        ]
    )
    networks = parse_scan(output)
    assert [(n.ssid, n.signal, n.secured, n.in_use) for n in networks] == [
        ("Home", 55, True, True),
        ("Camping", 65, False, False),
    ]


# --- housekeeping ------------------------------------------------------------------


def test_prune_history_keeps_recent_rows_and_distance(db):
    now = time.time()
    with transaction(db) as conn:
        for age_days in (100, 10):
            conn.execute(
                "INSERT INTO sensor_samples (sensor, ok, created_at) VALUES ('s', 1, ?)",
                (int(now - age_days * 86400),),
            )
        conn.execute(
            "INSERT INTO gps_distance_daily (day, distance_km, updated_at) "
            "VALUES ('2020-01-01', 5, 0)"
        )
    assert prune_history(db, retention_days=90, now=now) == 1
    with transaction(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM sensor_samples").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM gps_distance_daily").fetchone()[0] == 1


def test_worker_survives_exceptions():
    calls = []

    def task():
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("boom")

    worker = Worker("test", 0.01, task)
    worker.start()
    deadline = time.time() + 2
    while len(calls) < 3 and time.time() < deadline:
        time.sleep(0.01)
    worker.stop()
    status = worker.status()
    assert len(calls) >= 3
    assert "boom" in status.last_error
    assert status.running is False


def test_gps_counts_the_stop_segment_and_rejects_jumps(db):
    clock = Clock()
    gps = GpsService(receiver=None, db_path=db, clock=clock)
    gps.process(GpsFix(44.0, 17.0, speed_kmh=30))
    clock.now += 10
    gps.process(GpsFix(44.001, 17.0, speed_kmh=30))  # ~111 m
    clock.now += 10
    gps.process(GpsFix(45.0, 17.0, speed_kmh=30))  # 111 km in 10 s: bogus
    clock.now += 10
    gps.process(GpsFix(45.0005, 17.0, speed_kmh=30))  # segment restarts at the jump: ~55 m
    clock.now += 10
    gps.process(GpsFix(45.001, 17.0, speed_kmh=0))  # stopping: last ~55 m counts
    assert gps.total_distance_km() == pytest.approx(0.111 + 2 * 0.0556, abs=0.005)


def test_prune_skips_when_clock_jumped_forward(db):
    now = time.time()
    with transaction(db) as conn:
        conn.execute(
            "INSERT INTO sensor_samples (sensor, ok, created_at) VALUES ('s', 1, ?)", (int(now),)
        )
    assert prune_history(db, retention_days=90, now=now + 200 * 86400) == 0


def test_backup_once_per_day_keeps_three(db):
    from smartify.services.maintenance import backup, check_integrity

    assert check_integrity(db)
    day = 86400
    for i in range(5):
        assert backup(db, now=1_700_000_000 + i * day) is not None
    assert backup(db, now=1_700_000_000 + 4 * day) is None  # already done today
    assert len(list((db.parent / "backups").glob("*.db"))) == 3


def test_failsafe_command(tmp_path, monkeypatch):
    from smartify import failsafe
    from smartify.config import get_settings

    monkeypatch.setenv("SMARTIFY_DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    migrate(tmp_path / "smartify.db")
    with transaction(tmp_path / "smartify.db") as conn:
        conn.execute(
            "INSERT INTO relays (id, name, gpio_pin, created_at, updated_at) "
            "VALUES ('r', 'heater', 25, 0, 0)"
        )
    try:
        assert failsafe.main() == 0
    finally:
        get_settings.cache_clear()


def test_old_gps_points_are_archived_to_gpx_before_pruning(db, client):
    from smartify.services.gps_archive import archive_dir, list_archives

    now = time.time()
    old = int(now - 100 * 86400)
    with transaction(db) as conn:
        conn.execute(
            "INSERT INTO sensor_samples (sensor, ok, created_at) VALUES ('s', 1, ?)", (int(now),)
        )
        for i in range(3):
            conn.execute(
                "INSERT INTO gps_fixes (lat, lon, altitude_m, created_at) VALUES (?, ?, ?, ?)",
                (44.0 + i * 0.001, 17.0, 500.0, old + i * 10),
            )
    prune_history(db, retention_days=90, now=now)
    prune_history(db, retention_days=90, now=now)  # idempotent

    files = list_archives(db.parent)
    assert len(files) == 1
    content = (archive_dir(db.parent) / files[0]["name"]).read_text()
    assert content.count("<trkpt") == 3 and "<ele>500.0</ele>" in content
    with transaction(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM gps_fixes").fetchone()[0] == 0


def test_gps_archive_api(client, ctx):
    from smartify.services.gps_archive import archive_points

    archive_points(ctx.settings.data_dir, [(44.0, 17.0, None, 1_700_000_000)])
    files = client.get("/api/gps/archive").json()["files"]
    assert len(files) == 1
    response = client.get(f"/api/gps/archive/{files[0]['name']}")
    assert response.status_code == 200 and b"<trkpt" in response.content
    assert client.get("/api/gps/archive/..%2Fsmartify.db").status_code == 404
