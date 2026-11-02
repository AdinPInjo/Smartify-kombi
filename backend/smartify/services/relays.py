"""Relays: settings, manual/automatic control, and applying state to the hardware.

``reconcile`` is the only place that switches a relay. It works out the desired
state and drives the pin if that differs from the actual state:

* disabled relay: off
* ``manual`` mode: ``manual_state`` (until ``manual_until``, then back to auto)
* ``auto`` mode: the rules decide (see ``RuleService.decide``), limited by

  - the relay's ``min_on_seconds`` / ``min_off_seconds`` (protects devices from
    rapid switching), and
  - the ``cooldown_seconds`` of the rule that made the last change.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from smartify.config import Settings
from smartify.db import transaction
from smartify.hardware import HardwareError, RelayDriver
from smartify.services.rules import NotFound, RuleService

log = logging.getLogger(__name__)

State = Literal["on", "off"]
Source = Literal["boot", "manual", "rule", "auto", "remote"]

# Pins that may not drive relays: I2C (ADS1115) and the serial port (GPS).
RESERVED_PINS = {2: "I2C SDA", 3: "I2C SCL", 14: "UART TX (GPS)", 15: "UART RX (GPS)"}

_EDITABLE = {"label", "gpio_pin", "active_low", "enabled", "min_on_seconds", "min_off_seconds"}


class Conflict(ValueError):
    """The change is invalid in the current configuration (e.g. pin already used)."""


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
    state: State
    changed_at: int
    source: str
    reason: str | None
    rule_id: str | None
    updated_at: int
    revision: int
    last_error: str | None = None

    @classmethod
    def from_row(cls, row, last_error: str | None = None) -> Relay:
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
            state=row["actual_state"],
            changed_at=row["changed_at"],
            source=row["source"],
            reason=row["reason"],
            rule_id=row["rule_id"],
            updated_at=row["updated_at"],
            revision=row["revision"],
            last_error=last_error,
        )


_SELECT = (
    "SELECT r.*, s.actual_state, s.changed_at, s.source, s.reason, s.rule_id "
    "FROM relays r JOIN relay_state s ON s.relay_id = r.id"
)


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

    # --- queries ---------------------------------------------------------

    def list(self) -> list[Relay]:
        with transaction(self._db_path) as conn:
            rows = conn.execute(f"{_SELECT} ORDER BY r.created_at, r.name").fetchall()
        return [Relay.from_row(row, self._errors.get(row["id"])) for row in rows]

    def get(self, relay_id: str) -> Relay:
        with transaction(self._db_path) as conn:
            row = conn.execute(f"{_SELECT} WHERE r.id = ?", (relay_id,)).fetchone()
        if row is None:
            raise NotFound(f"relay {relay_id} not found")
        return Relay.from_row(row, self._errors.get(relay_id))

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
    ) -> Relay:
        with self._lock:
            self._check_pin(gpio_pin)
            now = int(self._clock())
            relay_id = str(uuid.uuid4())
            with transaction(self._db_path) as conn:
                if conn.execute("SELECT 1 FROM relays WHERE name = ?", (name,)).fetchone():
                    raise Conflict(f"a relay named '{name}' already exists")
                conn.execute(
                    "INSERT INTO relays (id, name, label, gpio_pin, active_low, enabled, "
                    "min_on_seconds, min_off_seconds, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        relay_id,
                        name,
                        label,
                        gpio_pin,
                        int(active_low),
                        int(enabled),
                        min_on_seconds,
                        min_off_seconds,
                        now,
                        now,
                    ),
                )
                conn.execute(
                    "INSERT INTO relay_state (relay_id, actual_state, changed_at, source, reason) "
                    "VALUES (?, 'off', ?, 'boot', 'created')",
                    (relay_id, now),
                )
            self._drive(relay_id, gpio_pin, active_low, on=False)
            self.reconcile(relay_id)
            return self.get(relay_id)

    def update(self, relay_id: str, changes: dict[str, Any]) -> Relay:
        unknown = set(changes) - _EDITABLE
        if unknown:
            raise ValueError(f"cannot change {', '.join(sorted(unknown))}")
        with self._lock:
            before = self.get(relay_id)
            if "gpio_pin" in changes and changes["gpio_pin"] != before.gpio_pin:
                self._check_pin(changes["gpio_pin"], ignore_relay=relay_id)
            if changes:
                self._write_settings(relay_id, changes)
            after = self.get(relay_id)
            if (after.gpio_pin, after.active_low) != (before.gpio_pin, before.active_low):
                # Release the old wiring before driving the new one.
                self._drive(relay_id, before.gpio_pin, before.active_low, on=False)
                self._drive(relay_id, after.gpio_pin, after.active_low, on=after.state == "on")
            self.reconcile(relay_id, force=True)
            return self.get(relay_id)

    def delete(self, relay_id: str) -> Relay:
        with self._lock:
            relay = self.get(relay_id)
            self._drive(relay_id, relay.gpio_pin, relay.active_low, on=False)
            with transaction(self._db_path) as conn:
                conn.execute("DELETE FROM relays WHERE id = ?", (relay_id,))
            self._errors.pop(relay_id, None)
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

    def set_auto(self, relay_id: str, source: Source = "manual") -> Relay:
        with self._lock:
            self.get(relay_id)
            self._write_settings(
                relay_id, {"mode": "auto", "manual_state": None, "manual_until": None}
            )
            self.reconcile(relay_id, force=True, source=source)
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
            # Known state first: whatever the pins did before the restart.
            for relay in self.list():
                self._drive(relay.id, relay.gpio_pin, relay.active_low, on=False)
                self._record(relay, "off", "boot", "startup", None)
            self.reconcile_all(force=True)

    def reconcile_all(self, force: bool = False) -> None:
        for relay in self.list():
            try:
                self.reconcile(relay.id, force=force)
            except Exception:
                log.exception("Reconciling relay %s failed", relay.name)

    def reconcile(self, relay_id: str, force: bool = False, source: Source | None = None) -> bool:
        """Bring the relay to its desired state. Returns True if the pin changed."""
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
            if not relay.enabled:
                desired: State | None = "off"
                reason, change_source = "relay disabled", source or "auto"
            elif relay.mode == "manual":
                desired = relay.manual_state or relay.state
                reason, change_source = "manual override", source or "manual"
            else:
                decision = self._rules.decide(relay_id)
                desired = decision.state
                reason, change_source = decision.reason, source or "auto"
                if decision.rule is not None:
                    rule_id = decision.rule.id
                    change_source = source or "rule"

            if desired is None or desired == relay.state:
                return False
            if not force and relay.mode == "auto" and self._held(relay, desired, now):
                return False

            if not self._drive(relay_id, relay.gpio_pin, relay.active_low, on=desired == "on"):
                return False
            self._record(relay, desired, change_source, reason, rule_id)
            if rule_id is not None:
                self._rules.mark_triggered(rule_id)
            log.info("%s %s -> %s (%s)", relay.name, relay.state, desired, reason)
            return True

    def _held(self, relay: Relay, desired: State, now: int) -> bool:
        """Is an automatic change blocked by switching protection?"""
        elapsed = now - relay.changed_at
        if relay.state == "on" and desired == "off" and elapsed < relay.min_on_seconds:
            return True
        if relay.state == "off" and desired == "on" and elapsed < relay.min_off_seconds:
            return True
        if relay.source == "rule" and relay.rule_id:
            try:
                cooldown = self._rules.get(relay.rule_id).cooldown_seconds
            except NotFound:
                return False
            return elapsed < cooldown
        return False

    def _drive(self, relay_id: str, gpio_pin: int, active_low: bool, on: bool) -> bool:
        try:
            self._driver.set_state(gpio_pin, on=on, active_low=active_low)
        except HardwareError as exc:
            self._errors[relay_id] = str(exc)
            log.error("Relay on GPIO %d: %s", gpio_pin, exc)
            return False
        self._errors.pop(relay_id, None)
        return True

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
