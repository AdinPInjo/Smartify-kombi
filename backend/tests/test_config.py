import pytest
from pydantic import ValidationError

from smartify.config import Settings


def test_defaults_are_safe_for_development():
    settings = Settings(_env_file=None)
    assert settings.hardware == "mock"
    assert settings.uses_default_credentials


def test_env_lists_are_parsed(monkeypatch):
    monkeypatch.setenv("SMARTIFY_DHT22_SENSORS", "kombi:5, garage:6")
    monkeypatch.setenv("SMARTIFY_DEFAULT_RELAYS", "heater:25,fan:26,pump:16")
    settings = Settings(_env_file=None)
    assert [(s.name, s.gpio_pin) for s in settings.dht22_sensors] == [("kombi", 5), ("garage", 6)]
    assert [(r.name, r.gpio_pin) for r in settings.default_relays] == [
        ("heater", 25),
        ("fan", 26),
        ("pump", 16),
    ]


def test_no_dht22_sensors(monkeypatch):
    monkeypatch.setenv("SMARTIFY_DHT22_SENSORS", "")
    assert Settings(_env_file=None).dht22_sensors == []


@pytest.mark.parametrize("value", ["heater", "heater:", "heater:99", "Big Heater:25"])
def test_invalid_relay_entries_are_rejected(monkeypatch, value):
    monkeypatch.setenv("SMARTIFY_DEFAULT_RELAYS", value)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)
