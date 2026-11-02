from __future__ import annotations

import pytest

from smartify.config import Settings
from smartify.db import migrate
from smartify.hardware.mock import MockRelayDriver
from smartify.services.conditions import MetricValue, SensorIssue, parse_condition
from smartify.services.relays import Conflict, RelayService
from smartify.services.rules import NotFound, RuleService


class FakeClock:
    def __init__(self, start: float = 1_000_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class FakeSensors:
    """Metric source the tests control directly."""

    def __init__(self) -> None:
        self.values: dict[tuple[str, str], MetricValue] = {}

    def set(self, sensor: str, metric: str, value: float | None, issue=None) -> None:
        self.values[(sensor, metric)] = MetricValue(value, issue)

    def __call__(self, sensor: str, metric: str) -> MetricValue:
        return self.values.get((sensor, metric), MetricValue(None, SensorIssue.MISSING))


@pytest.fixture
def env(tmp_path):
    settings = Settings(_env_file=None, data_dir=tmp_path)
    migrate(settings.db_path)
    clock = FakeClock()
    sensors = FakeSensors()
    driver = MockRelayDriver()
    rules = RuleService(settings.db_path, sensors, clock)
    relays = RelayService(settings, driver, rules, settings.db_path, clock)
    relays.startup()
    heater = next(r for r in relays.list() if r.name == "heater")

    class Env:
        pass

    e = Env()
    e.settings, e.clock, e.sensors, e.driver = settings, clock, sensors, driver
    e.rules, e.relays, e.heater = rules, relays, heater
    return e


def heat_below(value: float, **kwargs) -> dict:
    return {
        "name": f"heat below {value}",
        "condition": {
            "type": "threshold",
            "metric": "temperature",
            "sensor": "inside",
            "op": "<",
            "value": value,
        },
        "action": "on",
        **kwargs,
    }


# --- conditions ------------------------------------------------------------


@pytest.mark.parametrize(
    "bad",
    [
        {"type": "threshold", "metric": "temperature", "sensor": "inside", "op": "!=", "value": 1},
        {"type": "threshold", "metric": "humidity", "sensor": "inside", "op": "<", "value": 120},
        {"type": "range", "metric": "temperature", "sensor": "inside", "min": 10, "max": 5},
        {"type": "all", "conditions": []},
        {"type": "teleport"},
        "temperature < 5",
    ],
)
def test_invalid_conditions_are_rejected(bad):
    with pytest.raises(ValueError):
        parse_condition(bad)


def test_nesting_depth_is_limited():
    condition = {"type": "always"}
    for _ in range(5):
        condition = {"type": "not", "condition": condition}
    with pytest.raises(ValueError):
        parse_condition(condition)


# --- startup ---------------------------------------------------------------


def test_startup_seeds_default_relays_switched_off(env):
    names = {r.name: r for r in env.relays.list()}
    assert set(names) == {"heater", "fan"}
    assert all(r.state == "off" and r.mode == "auto" for r in names.values())
    assert env.driver.pin_levels == {25: False, 26: False}


def test_startup_does_not_reseed(env):
    env.relays.delete(env.heater.id)
    env.relays.startup()
    assert [r.name for r in env.relays.list()] == ["fan"]


# --- automatic control -------------------------------------------------------


def test_rule_switches_relay_and_back(env):
    env.rules.create(env.heater.id, **heat_below(8))
    env.sensors.set("inside", "temperature", 5.0)
    assert env.relays.reconcile(env.heater.id)
    relay = env.relays.get(env.heater.id)
    assert relay.state == "on" and relay.source == "rule"
    assert env.driver.is_on(25)

    env.clock.advance(120)  # past the rule cooldown
    env.sensors.set("inside", "temperature", 9.0)
    assert env.relays.reconcile(env.heater.id)
    assert env.relays.get(env.heater.id).state == "off"


def test_highest_priority_rule_wins(env):
    env.rules.create(env.heater.id, **heat_below(30, priority=10))
    env.rules.create(
        env.heater.id,
        name="never above 25",
        condition={
            "type": "range",
            "metric": "temperature",
            "sensor": "inside",
            "min": 25,
            "max": 80,
        },
        action="off",
        priority=50,
    )
    env.sensors.set("inside", "temperature", 26.0)
    env.relays.reconcile(env.heater.id)
    assert env.relays.get(env.heater.id).state == "off"
    decision = env.rules.decide(env.heater.id)
    assert decision.rule.name == "never above 25"
    assert [s.is_winner for s in decision.statuses] == [True, False]


def test_warming_up_sensor_keeps_state(env):
    env.rules.create(env.heater.id, **heat_below(8))
    env.sensors.set("inside", "temperature", None, SensorIssue.WARMING_UP)
    env.relays.set_manual(env.heater.id, "on")
    env.relays.set_auto(env.heater.id)  # sensor warming up: stays on
    env.relays.reconcile(env.heater.id)
    assert env.relays.get(env.heater.id).state == "on"


@pytest.mark.parametrize("issue", [SensorIssue.STALE, SensorIssue.MISSING])
def test_stale_or_missing_sensor_switches_off(env, issue):
    env.rules.create(env.heater.id, **heat_below(8))
    env.sensors.set("inside", "temperature", 5.0)
    env.relays.reconcile(env.heater.id)
    assert env.relays.get(env.heater.id).state == "on"

    env.clock.advance(120)
    env.sensors.set("inside", "temperature", None, issue)
    env.relays.reconcile(env.heater.id)
    relay = env.relays.get(env.heater.id)
    assert relay.state == "off"
    assert issue.value in relay.reason


def test_rule_cooldown_prevents_flapping(env):
    env.rules.create(env.heater.id, **heat_below(8, cooldown_seconds=300))
    env.sensors.set("inside", "temperature", 7.9)
    env.relays.reconcile(env.heater.id)
    env.sensors.set("inside", "temperature", 8.1)
    env.clock.advance(60)
    assert not env.relays.reconcile(env.heater.id)
    env.clock.advance(300)
    assert env.relays.reconcile(env.heater.id)


def test_min_off_time_protects_device(env):
    env.relays.update(env.heater.id, {"min_off_seconds": 600})
    env.rules.create(env.heater.id, **heat_below(8, cooldown_seconds=0))
    env.sensors.set("inside", "temperature", 5.0)
    env.clock.advance(60)  # relay switched off at startup 60 s ago
    assert not env.relays.reconcile(env.heater.id)
    env.clock.advance(600)
    assert env.relays.reconcile(env.heater.id)


def test_disabled_relay_stays_off(env):
    env.rules.create(env.heater.id, **heat_below(30))
    env.sensors.set("inside", "temperature", 5.0)
    env.relays.update(env.heater.id, {"enabled": False})
    env.relays.reconcile(env.heater.id)
    assert env.relays.get(env.heater.id).state == "off"


# --- manual control ----------------------------------------------------------


def test_manual_override_expires(env):
    env.relays.set_manual(env.heater.id, "on", duration_seconds=600)
    relay = env.relays.get(env.heater.id)
    assert relay.state == "on" and relay.mode == "manual"

    env.clock.advance(601)
    env.relays.reconcile(env.heater.id)
    relay = env.relays.get(env.heater.id)
    assert relay.mode == "auto"
    assert relay.state == "off"  # no rules -> off


def test_manual_ignores_switching_protection(env):
    env.relays.update(env.heater.id, {"min_off_seconds": 3600})
    env.relays.set_manual(env.heater.id, "on")
    assert env.relays.get(env.heater.id).state == "on"


def test_settings_changes_bump_revision(env):
    before = env.relays.get(env.heater.id).revision
    env.relays.set_manual(env.heater.id, "on")
    env.relays.update(env.heater.id, {"label": "Diesel heater"})
    assert env.relays.get(env.heater.id).revision == before + 2


def test_events_are_logged(env):
    env.relays.set_manual(env.heater.id, "on")
    events = env.relays.events(env.heater.id)
    assert events[0]["new_state"] == "on" and events[0]["source"] == "manual"


# --- wiring ----------------------------------------------------------------


def test_pin_conflicts_are_rejected(env):
    with pytest.raises(Conflict):
        env.relays.create(name="pump", gpio_pin=26)  # used by fan
    with pytest.raises(Conflict):
        env.relays.create(name="pump", gpio_pin=4)  # DHT22 'inside'
    with pytest.raises(Conflict):
        env.relays.create(name="pump", gpio_pin=2)  # I2C
    with pytest.raises(Conflict):
        env.relays.create(name="fan", gpio_pin=16)  # name taken


def test_changing_pin_releases_old_pin(env):
    env.relays.set_manual(env.heater.id, "on")
    env.relays.update(env.heater.id, {"gpio_pin": 16})
    assert env.driver.pin_levels[25] is False
    assert env.driver.pin_levels[16] is True


def test_active_low_inverts_pin(env):
    env.relays.update(env.heater.id, {"active_low": True})
    assert env.driver.pin_levels[25] is True  # off = high for active-low boards
    env.relays.set_manual(env.heater.id, "on")
    assert env.driver.pin_levels[25] is False


def test_hardware_error_is_reported_and_state_kept(env):
    env.driver.fail_pins.add(25)
    env.relays.set_manual(env.heater.id, "on")
    relay = env.relays.get(env.heater.id)
    assert relay.state == "off"
    assert "simulated failure" in relay.last_error


def test_deleting_relay_removes_its_rules(env):
    rule = env.rules.create(env.heater.id, **heat_below(8))
    env.relays.delete(env.heater.id)
    with pytest.raises(NotFound):
        env.rules.get(rule.id)
