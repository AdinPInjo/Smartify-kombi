"""Sensors tab: catalog, carrying over the old .env setup, live changes, inputs."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from smartify.config import Settings
from smartify.db import migrate, transaction
from smartify.hardware.base import ClimateReading
from smartify.hardware.pi.sensors import Ds18b20Sensor
from smartify.main import create_app
from smartify.services.inputs import InputService
from smartify.services.notify import NotificationService
from smartify.services.sensors import SensorStore

PASSWORD = "test-password"


def names(client) -> dict[str, str]:
    return {s["name"]: s["kind"] for s in client.get("/api/sensors").json()["sensors"]}


def test_demo_van_has_its_sensors(client):
    assert names(client) == {
        "inside": "dht22",
        "outside": "dht22",
        "gps": "gps",
        "tank": "water_tank",
    }
    data = client.get("/api/sensors").json()
    assert data["restart_required"] is False and data["available"] is True
    pins = {p["gpio"]: p for p in data["pins"]}
    assert pins[4]["used_by"] == "inside" and not pins[4]["free"]
    assert pins[2]["used_by"] == "I2C (SDA)"
    assert pins[22]["free"]


def test_add_probe_and_climate_sensor_live(client, ctx):
    found = client.get("/api/sensors/discover").json()
    assert found["onewire"]["probes"] and 0x76 in found["i2c"]["addresses"]
    probe = found["onewire"]["probes"][0]
    tried = client.post(
        "/api/sensors/test", json={"kind": "ds18b20", "config": {"rom": probe}}
    ).json()
    assert tried["ok"] and "°C" in tried["text"] and "%" not in tried["text"]

    fridge = client.post(
        "/api/sensors",
        json={"name": "fridge", "kind": "ds18b20", "config": {"rom": probe, "bus_pin": 22}},
    )
    assert fridge.status_code == 201, fridge.text
    assert "fridge" in ctx.climate.sensor_names  # live, no restart
    for _ in range(4):
        ctx.climate.sample()
    snapshot = next(s for s in ctx.climate.snapshots() if s.sensor == "fridge")
    assert snapshot.status == "ready" and snapshot.humidity is None
    ctx.climate.flush_minute()  # temperature-only rows are stored too

    bme = client.post(
        "/api/sensors", json={"name": "bed", "kind": "bme280", "config": {"address": "0x76"}}
    )
    assert bme.status_code == 201 and bme.json()["config"]["address"] == 0x76
    assert client.get("/api/sensors").json()["restart_required"] is False


def test_sensors_are_checked(client):
    def add(name, kind, config):
        return client.post("/api/sensors", json={"name": name, "kind": kind, "config": config})

    assert add("Bad Name", "dht22", {"pin": 22}).status_code == 422
    assert add("inside", "dht22", {"pin": 22}).status_code == 409  # name taken
    assert add("cabin", "dht22", {"pin": 4}).status_code == 409  # pin used by 'inside'
    assert add("cabin", "dht22", {"pin": 2}).status_code == 409  # I2C
    assert (
        add("cabin", "dht22", {"pin": 25}).json()["detail"]
        == "GPIO 25 is already used by relay 'heater'"
    )
    assert add("cabin", "unicorn", {}).status_code == 422
    assert add("probe", "ds18b20", {"rom": "nope"}).status_code == 422
    assert add("air", "sht31", {"address": 0x76}).status_code == 422  # not an SHT31 address
    assert add("gps2", "gps", {}).status_code == 409  # only one GPS


def test_relays_cannot_take_sensor_pins(client):
    response = client.post("/api/relays", json={"name": "pump", "gpio_pin": 4})
    assert response.status_code == 409 and "inside" in response.json()["detail"]


def test_gps_and_water_changes_need_a_restart(client):
    gps = next(s for s in client.get("/api/sensors").json()["sensors"] if s["kind"] == "gps")
    assert gps["needs_restart"]
    client.delete(f"/api/sensors/{gps['id']}")
    assert client.get("/api/sensors").json()["restart_required"] is True
    assert client.post("/api/system/restart").json()["restarting"] is False  # simulation


def test_rename_and_remove(client, ctx):
    inside = next(s for s in client.get("/api/sensors").json()["sensors"] if s["name"] == "inside")
    renamed = client.patch(
        f"/api/sensors/{inside['id']}", json={"name": "cabin", "config": {"pin": 22}}
    )
    assert renamed.status_code == 200 and renamed.json()["config"]["pin"] == 22
    assert "cabin" in ctx.climate.sensor_names and "inside" not in ctx.climate.sensor_names
    client.delete(f"/api/sensors/{inside['id']}")
    assert "cabin" not in ctx.climate.sensor_names


def test_door_and_motion(client, ctx):
    door = client.post(
        "/api/sensors", json={"name": "side_door", "kind": "door", "config": {"pin": 22}}
    )
    assert door.status_code == 201
    assert client.post("/api/sensors/test", json={"kind": "door", "config": {"pin": 22}}).json()[
        "ok"
    ]
    ctx.inputs.poll()
    state = ctx.inputs.states()[0]
    assert state["name"] == "side_door" and state["active"] is not None


class FakeInput:
    def __init__(self, name):
        self.name = name
        self.active = False

    def read(self):
        from smartify.hardware.base import InputState

        return InputState(self.active)


def test_door_alert_only_when_switched_on(tmp_path):
    migrate(tmp_path / "x.db")
    notifications = NotificationService(tmp_path / "x.db")
    service = InputService(notifications, clock=lambda: 1_800_000_000)
    door = FakeInput("side_door")
    service.set_inputs([(door, "door")])
    service.poll()
    door.active = True
    service.poll()
    assert notifications.recent() == []  # off by default
    notifications.update_settings({"alerts": {"door_open": {"enabled": True, "night_only": False}}})
    door.active = False
    service.poll()
    door.active = True
    service.poll()
    assert notifications.recent()[0]["title"] == "side_door: opened"


def test_fresh_install_starts_without_sensors(tmp_path):
    settings = Settings(
        _env_file=None, hardware="pi", data_dir=tmp_path, password="x" * 10, secret_key="s"
    )
    migrate(settings.db_path)
    assert SensorStore(settings.db_path).effective(settings) == []


def test_old_env_setup_is_carried_over_once(tmp_path):
    settings = Settings(
        _env_file=None,
        hardware="pi",
        data_dir=tmp_path,
        password="x" * 10,
        secret_key="s",
        dht22_sensors="cabin:5",
        gps_enabled=True,
    )
    migrate(settings.db_path)
    with transaction(settings.db_path) as conn:  # the water sender worked before
        conn.execute(
            "INSERT INTO water_level_samples (level_percent, battery_voltage, ok, created_at) "
            "VALUES (50, 12.8, 1, 1)"
        )
    store = SensorStore(settings.db_path)
    found = {s.name: (s.kind, s.config) for s in store.effective(settings)}
    assert found == {
        "cabin": ("dht22", {"pin": 5}),
        "gps": ("gps", {"device": "/dev/serial0", "baud": 9600}),
        "tank": ("water_tank", {}),
    }
    store.remove(next(s.id for s in store.all() if s.name == "cabin"))
    assert "cabin" not in {s.name for s in store.effective(settings)}  # not imported again


def test_ds18b20_reads_sysfs(tmp_path):
    probe = tmp_path / "28-0123456789ab"
    probe.mkdir()
    (probe / "w1_slave").write_text(
        "72 01 4b 46 7f ff 0e 10 57 : crc=57 YES\n72 01 4b 46 7f ff 0e 10 57 t=23125\n"
    )
    reading = Ds18b20Sensor("fridge", "28-0123456789ab", root=tmp_path).read()
    assert reading == ClimateReading("fridge", 23.12, None)
    (probe / "temperature").write_text("85000\n")
    assert (
        Ds18b20Sensor("fridge", "28-0123456789ab", root=tmp_path).read().error
        == "probe still starting"
    )
    assert "not found" in Ds18b20Sensor("x", "28-ffffffffffff", root=tmp_path).read().error


@pytest.fixture
def pi_less(tmp_path: Path):
    """A van with nothing but Victron and a heater: no sensors added."""
    settings = Settings(
        _env_file=None,
        hardware="mock",
        data_dir=tmp_path,
        password=PASSWORD,
        secret_key="s",
        weather_enabled=False,
    )
    migrate(settings.db_path)
    with transaction(settings.db_path) as conn:
        conn.execute("INSERT INTO sensor_setup (id, imported_at) VALUES (1, 1)")
    with TestClient(create_app(settings, start_workers=False)) as client:
        client.post("/api/auth/login", json={"username": "admin", "password": PASSWORD})
        yield client


def test_a_van_without_sensors_works(pi_less):
    assert pi_less.get("/api/sensors").json()["sensors"] == []
    assert pi_less.get("/api/climate").json()["sensors"] == []
    water = pi_less.get("/api/water").json()
    assert water["ok"] is False and "Sensors tab" in water["error"]
    assert pi_less.get("/api/gps").json()["status"] in ("disabled", "no_fix")


def test_diagnose_shows_reads_and_hints(client, ctx):
    inside = next(s for s in client.get("/api/sensors").json()["sensors"] if s["name"] == "inside")
    early = client.get(f"/api/sensors/{inside['id']}/diagnostics").json()
    assert early["hints"] == ["Collecting readings: give it a minute."]
    for _ in range(12):
        ctx.climate.sample()
    data = client.get(f"/api/sensors/{inside['id']}/diagnostics").json()
    assert data["reads"] == 12 and len(data["recent"]) == 12
    assert data["hints"]


def test_diagnose_explains_a_dead_sensor(client, ctx):
    from smartify.hardware import FailedSensor

    ctx.climate.set_sensors([FailedSensor("inside", "DHT sensor not found, check wiring")])
    for _ in range(6):
        ctx.climate.sample()
    inside = next(s for s in client.get("/api/sensors").json()["sensors"] if s["name"] == "inside")
    hints = client.get(f"/api/sensors/{inside['id']}/diagnostics").json()["hints"]
    assert "No reading at all" in hints[0] and "GPIO 4 (pin 7)" in hints[0]


def test_door_that_never_changed(client):
    door = client.post(
        "/api/sensors", json={"name": "side_door", "kind": "door", "config": {"pin": 22}}
    ).json()
    hints = client.get(f"/api/sensors/{door['id']}/diagnostics").json()["hints"]
    assert "Open and close the door" in hints[0]


def test_debug_mode_shows_detailed_logs_and_ends(client, ctx):
    assert client.get("/api/system/debug").json() == {"enabled": False, "until": None}
    on = client.post("/api/system/debug", json={"enabled": True, "hours": 1}).json()
    assert on["enabled"] and on["until"]
    ctx.climate.sample()
    debug_logs = client.get("/api/logs?level=DEBUG&limit=500").json()["logs"]
    assert any(r["level"] == "DEBUG" and r["message"].startswith("inside") for r in debug_logs)
    off = client.post("/api/system/debug", json={"enabled": False}).json()
    assert off["enabled"] is False
