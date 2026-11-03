"""Adding Victron devices from the dashboard."""

from __future__ import annotations

import pytest

from smartify.config import VictronDevice
from smartify.db import migrate
from smartify.errors import Conflict, InvalidInput
from smartify.services.victron_setup import VictronDevices, normalize_key, normalize_mac

KEY = "0123456789abcdef0123456789abcdef"
SHUNT_MAC = "C4:3A:BE:00:00:01"


def test_nearby_devices_with_suggested_names(client):
    data = client.get("/api/victron/nearby").json()
    assert data["bluetooth"] is True
    shunt = next(d for d in data["devices"] if d["kind"] == "battery_monitor")
    assert shunt["mac"] == SHUNT_MAC and shunt["suggested_name"] == "shunt"
    assert shunt["added_as"] is None


def test_add_check_and_remove_a_device(client):
    wrong = client.post(
        "/api/victron/devices", json={"name": "shunt", "mac": SHUNT_MAC, "key": "0" * 32}
    )
    assert wrong.status_code == 422 and "does not match" in wrong.json()["detail"]

    added = client.post(
        "/api/victron/devices",
        json={"name": "Shunt", "mac": "c4-3a-be-00-00-01", "key": KEY.upper()},
    )
    assert added.status_code == 201, added.text
    assert added.json()["key_checked"] is True
    devices = client.get("/api/victron/devices").json()["devices"]
    assert [(d["name"], d["mac"], d["source"]) for d in devices] == [
        ("shunt", SHUNT_MAC, "dashboard")
    ]

    nearby = client.get("/api/victron/nearby").json()["devices"]
    assert next(d for d in nearby if d["mac"] == SHUNT_MAC)["added_as"] == "shunt"
    again = client.post(
        "/api/victron/devices", json={"name": "other", "mac": SHUNT_MAC, "key": KEY}
    )
    assert again.status_code == 409

    # Rules can use it right away.
    relay = client.get("/api/relays").json()["relays"][0]
    condition = {
        "type": "threshold",
        "metric": "battery_soc",
        "sensor": "shunt",
        "op": ">",
        "value": 50,
    }
    response = client.post(
        f"/api/relays/{relay['id']}/rules",
        json={"name": "x", "condition": condition, "action": "on"},
    )
    assert response.status_code == 201, response.text

    assert client.delete("/api/victron/devices/shunt").json()["devices"] == []
    assert client.delete("/api/victron/devices/shunt").status_code == 404


def test_device_not_heard_yet_is_added_unchecked(client):
    added = client.post(
        "/api/victron/devices", json={"name": "far", "mac": "AA:BB:CC:DD:EE:FF", "key": KEY}
    )
    assert added.status_code == 201 and added.json()["key_checked"] is False


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ({"name": "Big Shunt", "mac": SHUNT_MAC, "key": KEY}, "name"),
        ({"name": "x", "mac": "C4:3A:BE", "key": KEY}, "12 hex digits"),
        ({"name": "x", "mac": SHUNT_MAC, "key": "abc"}, "32 characters"),
    ],
)
def test_invalid_input_is_explained(client, body, message):
    response = client.post("/api/victron/devices", json=body)
    assert response.status_code == 422 and message in response.json()["detail"]


def test_env_devices_are_listed_but_not_removable(tmp_path):
    db = tmp_path / "t.db"
    migrate(db)
    env = [VictronDevice(name="shunt", mac="AA:AA:AA:AA:AA:AA", key=KEY)]
    victron = VictronDevices(db, env, listener=None)
    assert [d.source for d in victron.configured()] == ["env"]
    with pytest.raises(Conflict):
        victron.remove("shunt")
    with pytest.raises(Conflict):
        victron.add("shunt", "BB:BB:BB:BB:BB:BB", KEY)
    assert victron.suggest_name("battery_monitor") == "shunt2"
    assert victron.error == "Bluetooth support is not installed"


def test_normalizing():
    assert normalize_mac("c43abe000001") == SHUNT_MAC
    assert normalize_key(" 0123 4567 89AB CDEF 0123 4567 89ab cdef ") == KEY
    with pytest.raises(InvalidInput):
        normalize_key("g" * 32)
