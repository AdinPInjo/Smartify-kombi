"""Door contacts and motion sensors: their state now, and an alert when they trigger.

Read every second by the "inputs" worker. An alert goes out when a door opens or
motion is seen, if that alert is on in the notification settings (off by
default, optionally only at night), at most once per 5 minutes per sensor.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from datetime import datetime
from typing import Any

from smartify.hardware.base import InputSensor
from smartify.services.notify import NotificationService, in_window

log = logging.getLogger(__name__)

ALERT_EVERY = 300


class _State:
    def __init__(self) -> None:
        self.active: bool | None = None
        self.error: str | None = None
        self.changed_at: int | None = None
        self.alerted_at = 0.0
        self.changes: list[tuple[int, bool]] = []
        self.reads = 0
        self.errors = 0


class InputService:
    def __init__(
        self,
        notifications: NotificationService,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._notify = notifications
        self._clock = clock
        self._lock = threading.Lock()
        self._inputs: list[tuple[InputSensor, str]] = []
        self._state: dict[str, _State] = {}

    def set_inputs(self, inputs: list[tuple[InputSensor, str]]) -> None:
        """``(sensor, kind)`` pairs, kind "door" or "motion"."""
        with self._lock:
            self._inputs = list(inputs)
            self._state = {s.name: self._state.get(s.name) or _State() for s, _ in inputs}

    def poll(self) -> None:
        for sensor, kind in list(self._inputs):
            reading = sensor.read()
            now = self._clock()
            with self._lock:
                state = self._state.get(sensor.name)
                if state is None:
                    continue
                changed = reading.active is not None and reading.active != state.active
                first = state.active is None
                state.error = reading.error
                state.reads += 1
                if reading.error:
                    state.errors += 1
                    log.debug("%s: %s", sensor.name, reading.error)
                if reading.active is not None:
                    state.active = reading.active
                if changed:
                    state.changed_at = int(now)
                    state.changes = ([(int(now), bool(reading.active))] + state.changes)[:20]
                    log.info(
                        "%s %s",
                        sensor.name,
                        ("open" if kind == "door" else "motion")
                        if reading.active
                        else ("closed" if kind == "door" else "quiet"),
                    )
            if changed and reading.active and not first:
                self._maybe_alert(sensor.name, kind, state, now)

    def _maybe_alert(self, name: str, kind: str, state: _State, now: float) -> None:
        alerts = self._notify.settings().alerts
        alert = alerts.door_open if kind == "door" else alerts.motion
        if not alert.enabled or now - state.alerted_at < ALERT_EVERY:
            return
        if alert.night_only and not in_window(
            datetime.fromtimestamp(now), alert.night_from, alert.night_to
        ):
            return
        state.alerted_at = now
        if kind == "door":
            self._notify.notify(
                f"door:{name}", f"{name}: opened", f"The {name} contact just opened.", "high"
            )
        else:
            self._notify.notify(
                f"motion:{name}", f"{name}: motion", f"Motion seen by {name}.", "high"
            )

    def diagnostics(self, name: str) -> dict[str, Any] | None:
        with self._lock:
            state = self._state.get(name)
            if state is None:
                return None
            return {
                "reads": state.reads,
                "good": state.reads - state.errors,
                "active": state.active,
                "error": state.error,
                "changes": [{"time": t, "active": a} for t, a in state.changes],
            }

    def states(self) -> list[dict[str, Any]]:
        with self._lock:
            return [
                {
                    "name": sensor.name,
                    "kind": kind,
                    "active": self._state[sensor.name].active,
                    "error": self._state[sensor.name].error,
                    "changed_at": self._state[sensor.name].changed_at,
                }
                for sensor, kind in self._inputs
                if sensor.name in self._state
            ]
