"""Water tank level and van battery voltage from the ADS1115.

Wiring (defaults):

* A0, signal: output of the tank level sender.
* A1, supply: the sender's supply (the van battery) through a voltage divider,
  47 kΩ on top and 10 kΩ to ground, so 14.4 V becomes about 2.5 V.

The battery voltage is reconstructed from A1. Because the sender is powered by
the battery, its output moves with the battery voltage; dividing the signal by
the supply (``ratio`` method) cancels that drift.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from statistics import fmean
from typing import Any, Literal

from smartify.db import transaction
from smartify.errors import InvalidInput
from smartify.hardware import AnalogReader, HardwareError
from smartify.services.conditions import MetricValue, SensorIssue

Method = Literal["voltage", "ratio"]

_SMOOTHING_SAMPLES = 6
# Below this the divider is probably disconnected; the ratio would be meaningless.
_MIN_BATTERY_VOLTAGE = 8.0


@dataclass(frozen=True)
class WaterSettings:
    method: Method
    signal_channel: int
    supply_channel: int
    divider_r_top: float
    divider_r_bottom: float
    empty_voltage: float
    full_voltage: float
    empty_ratio: float
    full_ratio: float
    updated_at: int
    revision: int

    def validate(self) -> None:
        if self.signal_channel == self.supply_channel:
            raise InvalidInput("signal and supply must use different ADC channels")
        if not {self.signal_channel, self.supply_channel} <= {0, 1, 2, 3}:
            raise InvalidInput("ADC channels are 0-3")
        if self.divider_r_top <= 0 or self.divider_r_bottom <= 0:
            raise InvalidInput("divider resistors must be positive")
        if abs(self.empty_voltage - self.full_voltage) < 0.01:
            raise InvalidInput("empty and full voltage must differ")
        if abs(self.empty_ratio - self.full_ratio) < 0.001:
            raise InvalidInput("empty and full ratio must differ")

    @property
    def divider_factor(self) -> float:
        return (self.divider_r_top + self.divider_r_bottom) / self.divider_r_bottom


@dataclass(frozen=True)
class WaterReading:
    ok: bool
    level_percent: int | None
    battery_voltage: float | None
    signal_voltage: float | None
    ratio: float | None
    error: str | None
    updated_at: int | None


def level_percent(value: float, empty: float, full: float) -> int:
    """Linear 0-100 % between the empty and full calibration points.

    Works in both directions (some senders read higher when full, some lower).
    """
    percent = (value - empty) / (full - empty) * 100.0
    return int(round(min(100.0, max(0.0, percent))))


_WIRING = {"signal_channel", "supply_channel", "divider_r_top", "divider_r_bottom"}

_EDITABLE = {
    "method",
    "signal_channel",
    "supply_channel",
    "divider_r_top",
    "divider_r_bottom",
    "empty_voltage",
    "full_voltage",
    "empty_ratio",
    "full_ratio",
}


class WaterService:
    def __init__(
        self,
        analog: AnalogReader,
        db_path: Path,
        clock: Callable[[], float] = time.time,
        stale_seconds: float = 120,
        enabled: bool = True,
    ) -> None:
        self.enabled = enabled
        """False: no water sender added in the Sensors tab."""
        self._analog = analog
        self._stale_seconds = stale_seconds
        self._db_path = db_path
        self._clock = clock
        self._lock = threading.Lock()
        self._recent: deque[tuple[float, float]] = deque(maxlen=_SMOOTHING_SAMPLES)
        self._minute: list[tuple[float, float]] = []
        self._minute_failures = 0
        self._last_error: str | None = None
        self._updated_at: int | None = None
        self._started_at = clock()

    # --- settings --------------------------------------------------------

    def settings(self) -> WaterSettings:
        with transaction(self._db_path) as conn:
            row = conn.execute("SELECT * FROM water_level_settings WHERE id = 1").fetchone()
        data = dict(row)
        data.pop("id")
        return WaterSettings(**data)

    def update_settings(self, changes: dict[str, Any]) -> WaterSettings:
        unknown = set(changes) - _EDITABLE
        if unknown:
            raise InvalidInput(f"cannot change {', '.join(sorted(unknown))}")
        current = self.settings()
        merged = {**current.__dict__, **changes}
        WaterSettings(**merged).validate()
        if changes:
            assignments = ", ".join(f"{column} = ?" for column in changes)
            with transaction(self._db_path) as conn:
                conn.execute(
                    f"UPDATE water_level_settings SET {assignments}, updated_at = ?, "
                    "revision = revision + 1 WHERE id = 1",
                    (*changes.values(), int(self._clock())),
                )
            if changes.keys() & _WIRING:
                with self._lock:
                    self._recent.clear()  # readings were taken with the old wiring
        return self.settings()

    def calibrate(self, point: Literal["empty", "full"]) -> WaterSettings:
        """Store the current (smoothed) reading as the empty or full point."""
        with self._lock:
            if not self._recent:
                raise InvalidInput("no sensor reading yet, cannot calibrate")
            signal = fmean(r[0] for r in self._recent)
            battery = fmean(r[1] for r in self._recent)
        if battery < _MIN_BATTERY_VOLTAGE:
            raise InvalidInput(f"supply reads {battery:.1f} V, check the divider wiring")
        return self.update_settings(
            {f"{point}_voltage": round(signal, 4), f"{point}_ratio": round(signal / battery, 5)}
        )

    # --- sampling --------------------------------------------------------

    def sample(self) -> None:
        if not self.enabled:
            return
        settings = self.settings()
        try:
            signal, supply_divided = self._analog.read_voltages(
                (settings.signal_channel, settings.supply_channel)
            )
        except HardwareError as exc:
            with self._lock:
                self._last_error = str(exc)
                self._minute_failures += 1
            return
        battery = supply_divided * settings.divider_factor
        with self._lock:
            self._recent.append((signal, battery))
            self._minute.append((signal, battery))
            self._last_error = None
            self._updated_at = int(self._clock())

    def current(self) -> WaterReading:
        if not self.enabled:
            return WaterReading(
                False, None, None, None, None, "no water sensor added (Sensors tab)", None
            )
        settings = self.settings()
        with self._lock:
            if not self._recent:
                return WaterReading(False, None, None, None, None, self._last_error, None)
            signal = fmean(r[0] for r in self._recent)
            battery = fmean(r[1] for r in self._recent)
            error, updated_at = self._last_error, self._updated_at
        if updated_at is not None and self._clock() - updated_at > self._stale_seconds:
            message = error or "no reading from the ADC for too long"
            return WaterReading(False, None, None, None, None, message, updated_at)
        return self._reading(settings, signal, battery, error, updated_at)

    def metric(self, sensor: str, metric: str) -> MetricValue:
        """Value source for rule conditions on ``water_level`` (sensor ``tank``)."""
        reading = self.current()
        if reading.ok and reading.level_percent is not None:
            return MetricValue(float(reading.level_percent))
        if reading.updated_at is None and self._clock() - self._started_at < self._stale_seconds:
            return MetricValue(None, SensorIssue.WARMING_UP)
        return MetricValue(None, SensorIssue.STALE)

    def _reading(
        self,
        settings: WaterSettings,
        signal: float,
        battery: float,
        error: str | None,
        updated_at: int | None,
    ) -> WaterReading:
        ratio = signal / battery if battery >= _MIN_BATTERY_VOLTAGE else None
        if settings.method == "ratio":
            if ratio is None:
                return WaterReading(
                    False,
                    None,
                    round(battery, 2),
                    round(signal, 4),
                    None,
                    f"supply reads {battery:.1f} V, check the divider wiring",
                    updated_at,
                )
            level = level_percent(ratio, settings.empty_ratio, settings.full_ratio)
        else:
            level = level_percent(signal, settings.empty_voltage, settings.full_voltage)
        return WaterReading(
            True,
            level,
            round(battery, 2),
            round(signal, 4),
            round(ratio, 5) if ratio is not None else None,
            error,
            updated_at,
        )

    def flush_minute(self) -> None:
        settings = self.settings()
        now = int(self._clock())
        with self._lock:
            minute, failures, error = self._minute, self._minute_failures, self._last_error
            self._minute, self._minute_failures = [], 0
        if minute:
            reading = self._reading(
                settings, fmean(r[0] for r in minute), fmean(r[1] for r in minute), None, now
            )
            row = (
                reading.signal_voltage,
                reading.battery_voltage,
                reading.ratio,
                reading.level_percent,
                int(reading.ok),
                reading.error,
                now,
            )
        elif failures:
            row = (None, None, None, None, 0, error, now)
        else:
            return
        with transaction(self._db_path) as conn:
            conn.execute(
                "INSERT INTO water_level_samples (signal_voltage, battery_voltage, ratio, "
                "level_percent, ok, error, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                row,
            )

    def history(self, since: int) -> list[dict]:
        with transaction(self._db_path) as conn:
            rows = conn.execute(
                "SELECT created_at, level_percent, battery_voltage FROM water_level_samples "
                "WHERE created_at >= ? AND ok = 1 ORDER BY created_at",
                (since,),
            ).fetchall()
        return [dict(row) for row in rows]
