"""End-to-end API tests against mock hardware."""

from __future__ import annotations

import math
import types

import pytest

HEAT_RULE = {
    "name": "Heat below 8",
    "condition": {
        "type": "threshold",
        "metric": "temperature",
        "sensor": "inside",
        "op": "<",
        "value": 8,
    },
    "action": "on",
}


def relay_by_name(client, name: str) -> dict:
    return next(r for r in client.get("/api/relays").json()["relays"] if r["name"] == name)


# --- auth --------------------------------------------------------------------


@pytest.mark.parametrize(
    "path", ["/api/relays", "/api/climate", "/api/water", "/api/gps", "/api/wifi", "/api/system"]
)
def test_endpoints_require_login(anon, path):
    assert anon.get(path).status_code == 401


def test_wrong_password_is_rejected(anon):
    response = anon.post("/api/auth/login", json={"username": "admin", "password": "nope"})
    assert response.status_code == 401


def test_login_me_logout(client):
    assert client.get("/api/auth/me").json()["user"] == "admin"
    client.post("/api/auth/logout")
    assert client.get("/api/auth/me").status_code == 401


# --- relays + rules ----------------------------------------------------------


def test_default_relays_exist(client):
    names = {r["name"]: r for r in client.get("/api/relays").json()["relays"]}
    assert set(names) == {"heater", "fan"}
    assert names["heater"]["gpio_pin"] == 25 and names["heater"]["state"] == "off"


def test_manual_control_and_back_to_auto(client, ctx):
    heater = relay_by_name(client, "heater")
    response = client.post(f"/api/relays/{heater['id']}/manual", json={"state": "on"})
    assert response.json()["state"] == "on"
    assert ctx.hardware.relays.is_on(25)

    response = client.post(f"/api/relays/{heater['id']}/auto")
    body = response.json()
    assert body["mode"] == "auto"
    assert body["state"] == "off"  # no rules


def test_relay_crud_and_validation(client):
    response = client.post("/api/relays", json={"name": "pump", "gpio_pin": 16})
    assert response.status_code == 201
    pump = response.json()

    assert client.post("/api/relays", json={"name": "pump2", "gpio_pin": 16}).status_code == 409
    assert client.post("/api/relays", json={"name": "Bad Name", "gpio_pin": 20}).status_code == 422

    response = client.patch(f"/api/relays/{pump['id']}", json={"label": "Water pump"})
    assert response.json()["label"] == "Water pump"

    assert client.delete(f"/api/relays/{pump['id']}").status_code == 200
    assert client.get(f"/api/relays/{pump['id']}").status_code == 404


def test_rule_lifecycle(client, ctx):
    heater = relay_by_name(client, "heater")
    response = client.post(f"/api/relays/{heater['id']}/rules", json=HEAT_RULE)
    assert response.status_code == 201
    rule = response.json()

    listing = client.get(f"/api/relays/{heater['id']}/rules").json()
    assert listing["rules"][0]["id"] == rule["id"]
    assert listing["rules"][0]["status"]["issue"] == "warming_up"  # no readings yet

    response = client.patch(f"/api/rules/{rule['id']}", json={"enabled": False})
    assert response.json()["enabled"] is False
    assert client.delete(f"/api/rules/{rule['id']}").status_code == 200


def test_invalid_rule_condition_is_422(client):
    heater = relay_by_name(client, "heater")
    bad = {**HEAT_RULE, "condition": {"type": "threshold", "metric": "pressure"}}
    response = client.post(f"/api/relays/{heater['id']}/rules", json=bad)
    assert response.status_code == 422


def test_rule_drives_relay_with_mock_sensors(client, ctx):
    """Full loop: sensor readings -> rule -> relay pin, as the workers would run it."""
    heater = relay_by_name(client, "heater")
    client.post(
        f"/api/relays/{heater['id']}/rules",
        json={**HEAT_RULE, "condition": {**HEAT_RULE["condition"], "value": 60}},
    )
    for sensor in ctx.hardware.climate_sensors:
        sensor._fail_rate = 0  # make the test deterministic
    for _ in range(ctx.settings.sensor_min_samples):
        ctx.climate.sample()
    ctx.relays.reconcile_all()
    assert relay_by_name(client, "heater")["state"] == "on"
    assert ctx.hardware.relays.is_on(25)


# --- sensors -------------------------------------------------------------------


def test_climate_snapshot_and_history(client, ctx):
    for sensor in ctx.hardware.climate_sensors:
        sensor._fail_rate = 0
    for _ in range(3):
        ctx.climate.sample()
    ctx.climate.flush_minute()

    sensors = {s["sensor"]: s for s in client.get("/api/climate").json()["sensors"]}
    assert set(sensors) == {"inside", "outside"}
    assert sensors["inside"]["status"] == "ready"

    history = client.get("/api/climate/inside/history?hours=1").json()["points"]
    assert len(history) == 1
    assert client.get("/api/climate/nope/history").status_code == 404


def test_water_level_battery_and_calibration(client, ctx, monkeypatch):
    # The simulated tank fills and empties with the clock; keep it half full here,
    # or calibrating "full" fails at the hours when it reads empty.
    import smartify.hardware.mock as mock_hardware

    monkeypatch.setattr(
        mock_hardware, "math", types.SimpleNamespace(sin=math.sin, cos=lambda _x: 0.0)
    )
    assert client.get("/api/water").json()["ok"] is False  # nothing sampled yet

    ctx.water.sample()
    reading = client.get("/api/water").json()
    assert reading["ok"] is True
    assert 0 <= reading["level_percent"] <= 100
    assert 12.0 < reading["battery_voltage"] < 14.0

    settings = client.post("/api/water/calibrate", json={"point": "full"}).json()
    assert settings["full_ratio"] == pytest.approx(reading["ratio"], abs=0.002)
    assert client.get("/api/water").json()["level_percent"] == 100

    response = client.patch("/api/water/settings", json={"supply_channel": 0})
    assert response.status_code == 422  # same channel as the signal


def test_gps(client, ctx):
    ctx.gps.poll()
    body = client.get("/api/gps").json()
    assert body["status"] == "ok"
    assert body["fix"]["satellites"] == 8
    assert len(client.get("/api/gps/track").json()["points"]) == 1
    assert "total_km" in client.get("/api/gps/distance").json()


def test_wifi_mock(client):
    assert client.get("/api/wifi").json()["ssid"] == "Kombi-Hotspot"
    networks = client.get("/api/wifi/networks").json()["networks"]
    assert networks[0]["in_use"] is True

    response = client.post("/api/wifi/connect", json={"ssid": "Cafe Bosna", "password": "wrong"})
    assert response.status_code == 400
    response = client.post("/api/wifi/connect", json={"ssid": "Cafe Bosna", "password": "kahva123"})
    assert response.json()["ssid"] == "Cafe Bosna"


def test_system_and_logs(client):
    system = client.get("/api/system").json()
    assert system["hardware"] == "mock"
    assert system["default_credentials"] is False
    logs = client.get("/api/logs?level=INFO").json()["logs"]
    assert any("Created default relay" in entry["message"] for entry in logs)
