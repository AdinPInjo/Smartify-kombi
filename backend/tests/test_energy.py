"""Victron decoding (real victron-ble with encrypted advertisements) and energy logic."""

from __future__ import annotations

import struct

import pytest
from Crypto.Cipher import AES
from Crypto.Util import Counter

from smartify.config import Settings
from smartify.db import migrate
from smartify.hardware import HardwareError, VictronReading
from smartify.hardware.mock import MockVictronListener
from smartify.hardware.victron import decode
from smartify.services.conditions import SensorIssue
from smartify.services.energy import EnergyService

KEY = "0df4d0395b7d1a876c0c33ecb9e70dcd"


class BitWriter:
    """Little-endian bit packing, the inverse of victron-ble's BitReader."""

    def __init__(self) -> None:
        self.value = 0
        self.bits = 0

    def write(self, value: int, bits: int) -> BitWriter:
        value &= (1 << bits) - 1
        self.value |= value << self.bits
        self.bits += bits
        return self

    def to_bytes(self) -> bytes:
        return self.value.to_bytes((self.bits + 7) // 8, "little")


def advertisement(mode: int, model_id: int, plaintext: bytes, key: str = KEY) -> bytes:
    """Build an encrypted Instant Readout advertisement, as a device would."""
    iv = 0x1234
    key_bytes = bytes.fromhex(key)
    counter = Counter.new(128, initial_value=iv, little_endian=True)
    padded = plaintext + b"\x00" * (-len(plaintext) % 16)
    encrypted = AES.new(key_bytes, AES.MODE_CTR, counter=counter).encrypt(padded)
    header = struct.pack("<HHBH", 0x0010, model_id, mode, iv)
    return header + key_bytes[:1] + encrypted[: len(plaintext)]


def smartshunt_payload() -> bytes:
    w = BitWriter()
    w.write(600, 16)  # remaining minutes
    w.write(1284, 16)  # 12.84 V
    w.write(0, 16)  # no alarm
    w.write(1256, 16)  # aux: starter battery 12.56 V
    w.write(0, 2)  # aux mode: starter voltage
    w.write(-4520, 22)  # -4.52 A
    w.write(948, 20)  # 94.8 Ah consumed
    w.write(842, 10)  # 84.2 %
    return w.to_bytes()


def test_decode_smartshunt_advertisement():
    data = advertisement(mode=0x02, model_id=0xA389, plaintext=smartshunt_payload())
    reading = decode("shunt", KEY, data, rssi=-60)
    assert reading.kind == "battery_monitor"
    assert reading.values["voltage"] == pytest.approx(12.84)
    assert reading.values["current"] == pytest.approx(-4.52)
    assert reading.values["soc"] == pytest.approx(84.2)
    assert reading.values["starter_voltage"] == pytest.approx(12.56)
    assert reading.values["alarm"] == "no_alarm"
    assert reading.rssi == -60


def test_decode_solar_charger_advertisement():
    w = BitWriter()
    w.write(3, 8).write(0, 8)  # bulk, no error
    w.write(1352, 16)  # 13.52 V
    w.write(125, 16)  # 12.5 A
    w.write(84, 16)  # 840 Wh today
    w.write(170, 16)  # 170 W
    w.write(0x1FF, 9)  # no load output
    reading = decode("solar", KEY, advertisement(0x01, 0xA05F, w.to_bytes()))
    assert reading.kind == "solar_charger"
    assert reading.values["solar_power"] == 170
    assert reading.values["yield_today"] == 840
    assert reading.values["charge_state"] == "bulk"


def test_decode_with_wrong_key_fails_cleanly():
    data = advertisement(0x02, 0xA389, smartshunt_payload())
    with pytest.raises(HardwareError, match="wrong encryption key"):
        decode("shunt", "ff" * 16, data)


class Clock:
    def __init__(self) -> None:
        self.now = 1_700_000_000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def energy(tmp_path):
    db = tmp_path / "t.db"
    migrate(db)
    clock = Clock()
    return EnergyService(db, stale_seconds=120, clock=clock), clock


def test_summary_prefers_the_shunt(energy):
    service, _ = energy
    for reading in MockVictronListener.readings(now=1_700_000_000):
        service.on_reading(reading)
    summary = service.summary()
    shunt = next(
        r for r in MockVictronListener.readings(1_700_000_000) if r.kind == "battery_monitor"
    )
    assert summary["available"]
    assert summary["battery"]["soc"] == shunt.values["soc"]
    assert summary["inverter"]["state"] == "inverting"
    assert {d.device for d in service.devices()} == {"shunt", "solar", "orion", "multiplus"}


def test_fallback_to_inverter_without_shunt(energy):
    service, _ = energy
    service.on_reading(
        VictronReading("multi", "inverter_charger", None, {"battery_voltage": 13.1, "soc": 70})
    )
    battery = service.summary()["battery"]
    assert battery["voltage"] == 13.1 and battery["soc"] == 70


def test_metric_staleness(energy):
    service, clock = energy
    assert service.metric("shunt", "battery_soc").issue is SensorIssue.WARMING_UP
    service.on_reading(VictronReading("shunt", "battery_monitor", None, {"soc": 42.0}))
    assert service.metric("shunt", "battery_soc").value == 42.0
    assert service.metric("shunt", "solar_power").issue is SensorIssue.MISSING
    clock.now += 121
    assert service.metric("shunt", "battery_soc").issue is SensorIssue.STALE
    assert service.metric("nope", "battery_soc").issue is SensorIssue.MISSING
    assert service.summary()["available"] is False


def test_history_is_averaged_per_minute(energy):
    service, _ = energy
    for soc in (40.0, 42.0):
        service.on_reading(
            VictronReading("shunt", "battery_monitor", None, {"soc": soc, "voltage": 12.8})
        )
    service.flush_minute()
    service.flush_minute()  # nothing new
    rows = service.history(0)
    assert len(rows) == 1
    assert rows[0]["battery_soc"] == pytest.approx(41.0)
    assert rows[0]["solar_power"] is None


def test_victron_config_parsing(monkeypatch):
    monkeypatch.setenv(
        "SMARTIFY_VICTRON_DEVICES",
        f"shunt|AA:BB:CC:DD:EE:01|{KEY}, solar|AA:BB:CC:DD:EE:02|{KEY}",
    )
    devices = Settings(_env_file=None).victron_devices
    assert [(d.name, d.mac) for d in devices] == [
        ("shunt", "AA:BB:CC:DD:EE:01"),
        ("solar", "AA:BB:CC:DD:EE:02"),
    ]
    assert KEY not in repr(devices[0])  # keys stay out of logs


def test_energy_api_and_battery_rule(client, ctx):
    for reading in MockVictronListener.readings():
        ctx.energy.on_reading(reading)
    body = client.get("/api/energy").json()
    assert body["available"] and len(body["devices"]) == 4

    heater = next(r for r in client.get("/api/relays").json()["relays"] if r["name"] == "heater")
    rule = {
        "name": "Low battery: heater off",
        "condition": {
            "type": "threshold",
            "metric": "battery_soc",
            "sensor": "shunt",
            "op": "<",
            "value": 20,
        },
        "action": "off",
        "priority": 500,
    }
    assert client.post(f"/api/relays/{heater['id']}/rules", json=rule).status_code == 201
    bad = {**rule, "condition": {**rule["condition"], "sensor": "inside"}}
    response = client.post(f"/api/relays/{heater['id']}/rules", json=bad)
    assert response.status_code == 422
    assert "for battery_soc" in response.json()["detail"]
