import pytest
from pydantic import ValidationError

from smartify.config import Settings


def test_defaults_are_safe_for_development():
    settings = Settings(_env_file=None)
    assert settings.hardware == "mock"
    assert settings.uses_default_credentials


def test_env_lists_are_parsed(monkeypatch):
    monkeypatch.setenv("SMARTIFY_DHT22_PINS", "5, 6")
    monkeypatch.setenv("SMARTIFY_DEFAULT_RELAYS", "heater:25,fan:26,pump:16")
    settings = Settings(_env_file=None)
    assert settings.dht22_pins == [5, 6]
    assert [(r.name, r.gpio_pin) for r in settings.default_relays] == [
        ("heater", 25),
        ("fan", 26),
        ("pump", 16),
    ]


def test_empty_dht22_pins(monkeypatch):
    monkeypatch.setenv("SMARTIFY_DHT22_PINS", "")
    assert Settings(_env_file=None).dht22_pins == []


@pytest.mark.parametrize("value", ["heater", "heater:", "heater:99"])
def test_invalid_relay_entries_are_rejected(monkeypatch, value):
    monkeypatch.setenv("SMARTIFY_DEFAULT_RELAYS", value)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)
