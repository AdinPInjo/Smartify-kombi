"""Relays: settings, manual/automatic control, and applying state to the hardware.

``reconcile`` is the only place that switches a relay. It works out the desired
state and drives the pin when either the stored state or the pin differs:

* disabled relay: off
* ``manual`` mode: ``manual_state`` (until ``manual_until``, then back to auto)
* ``auto`` mode: the rules decide (see ``RuleService.decide``), limited by

  - the relay's ``min_on_seconds`` / ``min_off_seconds`` (protects devices from
    rapid switching), and
  - the ``cooldown_seconds`` of the rule that made the last change.

Safety rules:

* Fail-safe "off" decisions (dead sensor, invalid rule, evaluation error,
  disabled relay) are never delayed by switching protection.
* The level last commanded to each pin is tracked in memory, separately from
  the database. If the two disagree (a failed DB write, a failed switch at
  boot) the next reconcile drives the pin again, so a relay cannot stay on
  while the database says off.
* Every relay is switched off at startup and at shutdown.
* Optional safety cutoff: above ``cutoff_max_c`` on ``cutoff_sensor`` the relay
  is forced off in every mode, manual included, until the temperature has
  dropped ``CUTOFF_HYSTERESIS_C`` below the limit.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from smartify.config import Settings
from smartify.db import transaction
from smartify.errors import Conflict, DeviceUnavailable, InvalidInput, NotFound
from smartify.hardware import HardwareError, RelayDriver
from smartify.services.rules import RuleService

log = logging.getLogger(__name__)

State = Literal["on", "off"]
Source = Literal["boot", "shutdown", "manual", "rule", "auto", "remote"]

# Pins that may not drive relays.
RESERVED_PINS = {
    0: "HAT EEPROM (ID_SD)",
    1: "HAT EEPROM (ID_SC)",
    2: "I2C SDA (ADS1115)",
    3: "I2C SCL (ADS1115)",
    14: "UART TX (GPS)",
    15: "UART RX (GPS)",
}

_EDITABLE = {
    "label",
    "gpio_pin",
    "active_low",
    "enabled",
    "min_on_seconds",
    "min_off_seconds",
    "cutoff_sensor",
    "cutoff_max_c",
}
_FORCE_ON_CHANGE = {"gpio_pin", "active_low", "enabled", "cutoff_sensor", "cutoff_max_c"}

CUTOFF_HYSTERESIS_C = 1.0


@dataclass(frozen=True)
class Relay:
    id: str
    name: str
    label: str | None
    gpio_pin: int
    active_low: bool
    enabled: bool
    mode: Literal["auto", "manual"]
    manual_state: State | None
    manual_until: int | None
    min_on_seconds: int
    min_off_seconds: int
    cutoff_sensor: str | None
    cutoff_max_c: float | None
    state: State
    changed_at: int
    source: str
    reason: str | None
    rule_id: str | None
    updated_at: int
    revision: int
    last_error: str | None = None
    """Last hardware error while switching this relay, if the last attempt failed."""
    pending: str | None = None
    """Why the relay is not (yet) in the state the rules want, e.g. min on time."""
    explanation: str | None = None
    """Why the relay should be in its state right now (from the latest evaluation)."""

    @classmethod
    def from_row(
        cls,
        row,
        last_error: str | None = None,
        pending: str | None = None,
        explanation: str | None = None,
    ) -> Relay:
        return cls(
            id=row["id"],
            name=row["name"],
            label=row["label"],
            gpio_pin=row["gpio_pin"],
            active_low=bool(row["active_low"]),
            enabled=bool(row["enabled"]),
            mode=row["mode"],
            manual_state=row["manual_state"],
            manual_until=row["manual_until"],
            min_on_seconds=row["min_on_seconds"],
            min_off_seconds=row["min_off_seconds"],
            cutoff_sensor=row["cutoff_sensor"],
            cutoff_max_c=row["cutoff_max_c"],
            state=row["actual_state"],
            changed_at=row["changed_at"],
            source=row["source"],
            reason=row["reason"],
            rule_id=row["rule_id"],
            updated_at=row["updated_at"],
            revision=row["revision"],
            last_error=last_error,
            pending=pending,
            explanation=explanation,
        )


_SELECT = (
    "SELECT r.*, s.actual_state, s.changed_at, s.source, s.reason, s.rule_id "
    "FROM relays r JOIN relay_state s ON s.relay_id = r.id"
)


def _minutes(seconds: int) -> str:
    return f"{seconds // 60} min {seconds % 60} s" if seconds >= 60 else f"{seconds} s"


class RelayService:
    def __init__(
        self,
        settings: Settings,
        driver: RelayDriver,
        rules: RuleService,
        db_path: Path,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._settings = settings
        self._driver = driver
        self._rules = rules
        self._db_path = db_path
        self._clock = clock
        # One relay switches at a time; keeps decide-and-apply atomic.
        self._lock = threading.RLock()
        self._errors: dict[str, str] = {}
        self._pending: dict[str, str] = {}
        # Level last successfully commanded per relay. Missing = unknown.
        self._levels: dict[str, State] = {}
        # Latest decision reason per relay, shown in the dashboard.
        self._explain: dict[str, str] = {}
        # Relays whose temperature cutoff has tripped (cleared with hysteresis).
        self._tripped: set[str] = set()

    # --- queries ---------------------------------------------------------

    def _from_row(self, row) -> Relay:
        relay_id = row["id"]
        return Relay.from_row(
            row,
            self._errors.get(relay_id),
            self._pending.get(relay_id),
            self._explain.get(relay_id),
        )

    def list(self) -> list[Relay]:
        with transaction(self._db_path) as conn:
            rows = conn.execute(f"{_SELECT} ORDER BY r.created_at, r.name").fetchall()
        return [self._from_row(row) for row in rows]

    def get(self, relay_id: str) -> Relay:
        with transaction(self._db_path) as conn:
            row = conn.execute(f"{_SELECT} WHERE r.id = ?", (relay_id,)).fetchone()
        if row is None:
            raise NotFound(f"relay {relay_id} not found")
        return self._from_row(row)

    def events(self, relay_id: str, limit: int = 50) -> list[dict[str, Any]]:
        self.get(relay_id)
        with transaction(self._db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM relay_events WHERE relay_id = ? ORDER BY id DESC LIMIT ?",
                (relay_id, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    # --- settings --------------------------------------------------------

    def create(
        self,
        *,
        name: str,
        gpio_pin: int,
        label: str | None = None,
        active_low: bool = False,
        enabled: bool = True,
        min_on_seconds: int = 0,
        min_off_seconds: int = 0,
        cutoff_sensor: str | None = None,
        cutoff_max_c: float | None = None,
    ) -> Relay:
        with self._lock:
            self._check_pin(gpio_pin)
            self._check_cutoff(cutoff_sensor, cutoff_max_c)
            now = int(self._clock())
            relay_id = str(uuid.uuid4())
            try:
                with transaction(self._db_path) as conn:
                    conn.execute(
                        "INSERT INTO relays (id, name, label, gpio_pin, active_low, enabled, "
                        "min_on_seconds, min_off_seconds, cutoff_sensor, cutoff_max_c, "
                        "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            relay_id,
                            name,
                            label,
                            gpio_pin,
                            int(active_low),
                            int(enabled),
                            min_on_seconds,
                            min_off_seconds,
                            cutoff_sensor,
                            cutoff_max_c,
                            now,
                            now,
                        ),
                    )
                    conn.execute(
                        "INSERT INTO relay_state "
                        "(relay_id, actual_state, changed_at, source, reason) "
                        "VALUES (?, 'off', ?, 'boot', 'created')",
                        (relay_id, now),
                    )
            except sqlite3.IntegrityError as exc:
                raise Conflict(f"a relay named '{name}' already exists") from exc
            self.reconcile(relay_id, force=True)
            return self.get(relay_id)

    def update(self, relay_id: str, changes: dict[str, Any]) -> Relay:
        unknown = set(changes) - _EDITABLE
        if unknown:
            raise InvalidInput(f"cannot change {', '.join(sorted(unknown))}")
        with self._lock:
            before = self.get(relay_id)
            rewired = ("gpio_pin" in changes and changes["gpio_pin"] != before.gpio_pin) or (
                "active_low" in changes and changes["active_low"] != before.active_low
            )
            if "gpio_pin" in changes and changes["gpio_pin"] != before.gpio_pin:
                self._check_pin(changes["gpio_pin"], ignore_relay=relay_id)
            if changes.keys() & {"cutoff_sensor", "cutoff_max_c"}:
                self._check_cutoff(
                    changes.get("cutoff_sensor", before.cutoff_sensor),
                    changes.get("cutoff_max_c", before.cutoff_max_c),
                )
                self._tripped.discard(relay_id)
            if rewired:
                # Release the old wiring first; if that fails, change nothing.
                self._drive_or_raise(before.gpio_pin, before.active_low, on=False)
                self._levels.pop(relay_id, None)  # new wiring: level unknown
            if changes:
                self._write_settings(relay_id, changes)
            force = bool(changes.keys() & _FORCE_ON_CHANGE)
            self.reconcile(relay_id, force=force)
            return self.get(relay_id)

    def delete(self, relay_id: str) -> Relay:
        with self._lock:
            relay = self.get(relay_id)
            # Never forget a pin that may still be on.
            self._drive_or_raise(relay.gpio_pin, relay.active_low, on=False)
            with transaction(self._db_path) as conn:
                conn.execute("DELETE FROM relays WHERE id = ?", (relay_id,))
            for store in (self._errors, self._pending, self._levels, self._explain):
                store.pop(relay_id, None)
            self._tripped.discard(relay_id)
            return relay

    def set_manual(
        self,
        relay_id: str,
        state: State,
        duration_seconds: int | None = None,
        source: Source = "manual",
    ) -> Relay:
        until = int(self._clock()) + duration_seconds if duration_seconds else None
        with self._lock:
            self.get(relay_id)
            self._write_settings(
                relay_id, {"mode": "manual", "manual_state": state, "manual_until": until}
            )
            self.reconcile(relay_id, force=True, source=source)
            return self.get(relay_id)

    def set_auto(self, relay_id: str) -> Relay:
        with self._lock:
            self.get(relay_id)
            self._write_settings(
                relay_id, {"mode": "auto", "manual_state": None, "manual_until": None}
            )
            self.reconcile(relay_id, force=True)
            return self.get(relay_id)

    def _write_settings(self, relay_id: str, columns: dict[str, Any]) -> None:
        values = {k: int(v) if isinstance(v, bool) else v for k, v in columns.items()}
        assignments = ", ".join(f"{column} = ?" for column in values)
        with transaction(self._db_path) as conn:
            conn.execute(
                f"UPDATE relays SET {assignments}, updated_at = ?, revision = revision + 1 "
                "WHERE id = ?",
                (*values.values(), int(self._clock()), relay_id),
            )

    def _check_cutoff(self, sensor: str | None, max_c: float | None) -> None:
        if (sensor is None) != (max_c is None):
            raise InvalidInput("set both cutoff_sensor and cutoff_max_c, or neither")
        names = self._rules.sensors_for("temperature")
        if sensor is not None and sensor not in names:
            known = ", ".join(names) or "none configured"
            raise InvalidInput(f"unknown sensor {sensor} (available: {known})")

    def _cutoff_reason(self, relay: Relay) -> str | None:
        """The safety cutoff's verdict: a reason to force the relay off, or None."""
        if relay.cutoff_sensor is None or relay.cutoff_max_c is None:
            self._tripped.discard(relay.id)
            return None
        reading = self._rules.metric_source(relay.cutoff_sensor, "temperature")
        limit = relay.cutoff_max_c
        if reading.value is not None:
            if reading.value > limit:
                self._tripped.add(relay.id)
            elif reading.value <= limit - CUTOFF_HYSTERESIS_C:
                self._tripped.discard(relay.id)
        # No reading: keep the last verdict (the rules handle dead sensors in auto).
        if relay.id in self._tripped:
            return f"safety cutoff: {relay.cutoff_sensor} above {limit:g} °C"
        return None

    def _check_pin(self, gpio_pin: int, ignore_relay: str | None = None) -> None:
        if gpio_pin in RESERVED_PINS:
            raise Conflict(f"GPIO {gpio_pin} is reserved for {RESERVED_PINS[gpio_pin]}")
        sensors = {s.gpio_pin: s.name for s in self._settings.dht22_sensors}
        if gpio_pin in sensors:
            raise Conflict(f"GPIO {gpio_pin} is used by sensor '{sensors[gpio_pin]}'")
        with transaction(self._db_path) as conn:
            row = conn.execute(
                "SELECT name FROM relays WHERE gpio_pin = ? AND id IS NOT ?",
                (gpio_pin, ignore_relay),
            ).fetchone()
        if row:
            raise Conflict(f"GPIO {gpio_pin} is already used by relay '{row['name']}'")

    # --- control ---------------------------------------------------------

    def startup(self) -> None:
        """Create default relays on first start, switch everything off, then reconcile."""
        with self._lock:
            if not self.list():
                for seed in self._settings.default_relays:
                    try:
                        self.create(name=seed.name, gpio_pin=seed.gpio_pin)
                        log.info("Created default relay %s on GPIO %d", seed.name, seed.gpio_pin)
                    except Conflict as exc:
                        log.error("Default relay %s not created: %s", seed.name, exc)
            self.all_off("boot", "startup")
            self.reconcile_all(force=True)

    def all_off(self, source: Source, reason: str) -> None:
        """Switch every relay off (startup and shutdown). Best effort, never raises."""
        with self._lock:
            for relay in self.list():
                if not self._drive(relay.id, relay.gpio_pin, relay.active_low, on=False):
                    continue  # level stays unknown; reconcile keeps retrying
                if relay.state != "off":
                    try:
                        self._record(relay, "off", source, reason, None)
                    except sqlite3.Error:
                        log.exception("Could not record %s as off", relay.name)

    def reconcile_all(self, force: bool = False) -> None:
        for relay in self.list():
            try:
                self.reconcile(relay.id, force=force)
            except NotFound:
                pass  # deleted meanwhile
            except Exception:
                log.exception("Reconciling relay %s failed", relay.name)

    def reconcile(self, relay_id: str, force: bool = False, source: Source | None = None) -> bool:
        """Bring the relay to its desired state. Returns True if the pin was driven."""
        with self._lock:
            relay = self.get(relay_id)
            now = int(self._clock())

            if (
                relay.mode == "manual"
                and relay.manual_until is not None
                and now >= relay.manual_until
            ):
                self._write_settings(
                    relay_id, {"mode": "auto", "manual_state": None, "manual_until": None}
                )
                relay = self.get(relay_id)
                log.info("Manual override of %s expired, back to auto", relay.name)

            rule_id: str | None = None
            fail_safe = False
            cutoff = self._cutoff_reason(relay)
            if not relay.enabled:
                desired: State | None = "off"
                reason, change_source = "relay disabled", source or "auto"
                fail_safe = True
            elif cutoff is not None:
                desired, reason, change_source = "off", cutoff, source or "auto"
                fail_safe = True
            elif relay.mode == "manual":
                desired = relay.manual_state or "off"
                reason, change_source = "manual override", source or "manual"
            else:
                decision = self._rules.decide(relay_id)
                desired, reason, fail_safe = decision.state, decision.reason, decision.fail_safe
                change_source = source or "auto"
                if decision.rule is not None:
                    rule_id = decision.rule.id
                    change_source = source or "rule"

            self._explain[relay_id] = reason
            level = self._levels.get(relay_id)
            if desired is None:
                if level is not None:
                    self._pending.pop(relay_id, None)
                    return False
                # Holding, but the pin level is unknown: make it safe.
                desired, reason, fail_safe = "off", "pin state unknown", True

            if desired == relay.state and level == desired:
                self._pending.pop(relay_id, None)
                return False

            if desired != relay.state and not (force or fail_safe) and relay.mode == "auto":
                held = self._hold_reason(relay, desired, now)
                if held is not None:
                    self._pending[relay_id] = held
                    if level is None:
                        # Keep the recorded state, but make sure the pin matches it.
                        self._drive(relay_id, relay.gpio_pin, relay.active_low, relay.state == "on")
                    return False
            self._pending.pop(relay_id, None)

            if not self._drive(relay_id, relay.gpio_pin, relay.active_low, on=desired == "on"):
                return False
            if desired != relay.state:
                self._record(relay, desired, change_source, reason, rule_id)
                if rule_id is not None:
                    self._rules.mark_triggered(rule_id)
                log.info("%s %s -> %s (%s)", relay.name, relay.state, desired, reason)
            return True

    def _hold_reason(self, relay: Relay, desired: State, now: int) -> str | None:
        """Why an automatic change has to wait, or None if it may happen now."""
        elapsed = now - relay.changed_at
        if elapsed < 0:
            return None  # the clock jumped backwards; don't hold for hours
        if relay.state == "on" and desired == "off" and elapsed < relay.min_on_seconds:
            return f"minimum on time, {_minutes(relay.min_on_seconds - elapsed)} left"
        if relay.state == "off" and desired == "on" and elapsed < relay.min_off_seconds:
            return f"minimum off time, {_minutes(relay.min_off_seconds - elapsed)} left"
        if relay.source == "rule" and relay.rule_id:
            try:
                rule = self._rules.get(relay.rule_id)
            except NotFound:
                return None
            if elapsed < rule.cooldown_seconds:
                left = _minutes(rule.cooldown_seconds - elapsed)
                return f"cooldown of rule '{rule.name}', {left} left"
        return None

    def _drive(self, relay_id: str, gpio_pin: int, active_low: bool, on: bool) -> bool:
        try:
            self._driver.set_state(gpio_pin, on=on, active_low=active_low)
        except HardwareError as exc:
            self._errors[relay_id] = str(exc)
            self._levels.pop(relay_id, None)  # we no longer know the pin level
            log.error("Relay on GPIO %d: %s", gpio_pin, exc)
            return False
        self._errors.pop(relay_id, None)
        self._levels[relay_id] = "on" if on else "off"
        return True

    def _drive_or_raise(self, gpio_pin: int, active_low: bool, on: bool) -> None:
        try:
            self._driver.set_state(gpio_pin, on=on, active_low=active_low)
        except HardwareError as exc:
            raise DeviceUnavailable(f"could not switch GPIO {gpio_pin}: {exc}") from exc

    def _record(
        self, relay: Relay, new_state: State, source: str, reason: str, rule_id: str | None
    ) -> None:
        now = int(self._clock())
        with transaction(self._db_path) as conn:
            conn.execute(
                "UPDATE relay_state SET actual_state = ?, changed_at = ?, source = ?, "
                "reason = ?, rule_id = ? WHERE relay_id = ?",
                (new_state, now, source, reason, rule_id, relay.id),
            )
            conn.execute(
                "INSERT INTO relay_events "
                "(relay_id, source, rule_id, old_state, new_state, reason, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (relay.id, source, rule_id, relay.state, new_state, reason, now),
            )
