"""Temperature and humidity from the DHT22 sensors.

Raw DHT22 readings are noisy and fail now and then. Rules therefore never see a
single reading: each sensor keeps a rolling window of good readings and exposes
the average. A sensor is

* ``warming_up`` until it has ``sensor_min_samples`` good readings,
* ``ready`` while its last good reading is younger than ``sensor_stale_seconds``
  (short dropouts keep the last average),
* ``stale`` after that.

Once a minute the readings of that minute are averaged and stored, which keeps
SD card writes low (one row per sensor per minute).
"""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from statistics import fmean
from typing import Literal

from smartify.config import Settings
from smartify.db import transaction
from smartify.hardware import ClimateSensor
from smartify.services.conditions import MetricValue, SensorIssue

Status = Literal["ready", "warming_up", "stale"]

# DHT22 specification limits. Anything outside is a corrupted read.
_TEMPERATURE_RANGE = (-40.0, 80.0)
_HUMIDITY_RANGE = (0.0, 100.0)


def _plausible(temperature: float | None, humidity: float | None) -> bool:
    """Humidity may be None: temperature-only probes (DS18B20) have none."""
    if temperature is None:
        return False
    if not _TEMPERATURE_RANGE[0] <= temperature <= _TEMPERATURE_RANGE[1]:
        return False
    return humidity is None or _HUMIDITY_RANGE[0] <= humidity <= _HUMIDITY_RANGE[1]


def _mean(values: list[float | None]) -> float | None:
    present = [v for v in values if v is not None]
    return round(fmean(present), 2) if present else None


@dataclass(frozen=True)
class ClimateSnapshot:
    sensor: str
    status: Status
    temperature_c: float | None
    humidity: float | None
    sample_count: int
    last_good_at: int | None
    last_error: str | None


class _SensorState:
    def __init__(self) -> None:
        self.window: deque[tuple[float, float, float]] = deque()
        self.minute: list[tuple[float, float]] = []
        self.minute_failures = 0
        self.last_error: str | None = None
        self.last_good_at: float | None = None
        self.good_total = 0
        self.temperature: float | None = None
        self.humidity: float | None = None


class ClimateService:
    def __init__(
        self,
        settings: Settings,
        sensors: list[ClimateSensor],
        db_path: Path,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._settings = settings
        self._sensors = sensors
        self._db_path = db_path
        self._clock = clock
        self._lock = threading.Lock()
        self._state = {sensor.name: _SensorState() for sensor in sensors}
        self._started_at = clock()

    @property
    def sensor_names(self) -> list[str]:
        return [sensor.name for sensor in self._sensors]

    def set_sensors(self, sensors: list[ClimateSensor]) -> None:
        """Sensors added, changed or removed in the dashboard: keep the others' readings."""
        with self._lock:
            self._sensors = list(sensors)
            self._state = {s.name: self._state.get(s.name) or _SensorState() for s in sensors}

    # --- sampling --------------------------------------------------------

    def sample(self) -> None:
        """Read every sensor once. Called by the climate worker."""
        for sensor in list(self._sensors):
            reading = sensor.read()
            now = self._clock()
            with self._lock:
                state = self._state.get(sensor.name)
                if state is None:  # removed while reading
                    continue
                if reading.ok and _plausible(reading.temperature_c, reading.humidity):
                    state.window.append((now, reading.temperature_c, reading.humidity))
                    state.minute.append((reading.temperature_c, reading.humidity))
                    state.last_good_at = now
                    state.good_total += 1
                    state.last_error = None
                else:
                    state.minute_failures += 1
                    state.last_error = reading.error or (
                        f"implausible reading {reading.temperature_c} °C / {reading.humidity} %"
                    )
                self._prune(state, now)
                # Only replace the average once the window holds enough readings;
                # after a dropout one fresh reading must not decide on its own.
                if len(state.window) >= self._settings.sensor_min_samples:
                    state.temperature = _mean([r[1] for r in state.window])
                    state.humidity = _mean([r[2] for r in state.window])

    def _prune(self, state: _SensorState, now: float) -> None:
        cutoff = now - self._settings.sensor_window_seconds
        while state.window and state.window[0][0] < cutoff:
            state.window.popleft()

    def flush_minute(self) -> None:
        """Store the average of the readings since the last flush."""
        now = int(self._clock())
        rows = []
        with self._lock:
            for name, state in self._state.items():
                if state.minute:
                    temperature = _mean([r[0] for r in state.minute])
                    humidity = _mean([r[1] for r in state.minute])
                    rows.append((name, temperature, humidity, 1, None, now))
                elif state.minute_failures:
                    rows.append((name, None, None, 0, state.last_error, now))
                state.minute.clear()
                state.minute_failures = 0
        if rows:
            with transaction(self._db_path) as conn:
                conn.executemany(
                    "INSERT INTO sensor_samples "
                    "(sensor, temperature_c, humidity, ok, error, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    rows,
                )

    # --- reading ---------------------------------------------------------

    def snapshot(self, sensor: str) -> ClimateSnapshot | None:
        with self._lock:
            state = self._state.get(sensor)
            if state is None:
                return None
            now = self._clock()
            self._prune(state, now)
            return ClimateSnapshot(
                sensor=sensor,
                status=self._status(state, now),
                temperature_c=state.temperature,
                humidity=state.humidity,
                sample_count=len(state.window),
                last_good_at=int(state.last_good_at) if state.last_good_at else None,
                last_error=state.last_error,
            )

    def snapshots(self) -> list[ClimateSnapshot]:
        return [snap for name in self.sensor_names if (snap := self.snapshot(name))]

    def _status(self, state: _SensorState, now: float) -> Status:
        stale_after = self._settings.sensor_stale_seconds
        if state.last_good_at is not None:
            if now - state.last_good_at > stale_after:
                return "stale"
            if state.temperature is None:  # never had a full window yet
                return "warming_up"
            return "ready"
        # Never had a good reading: give the sensor time before calling it stale.
        return "stale" if now - self._started_at > stale_after else "warming_up"

    def metric(self, sensor: str, metric: str) -> MetricValue:
        """Value source for rule conditions."""
        snap = self.snapshot(sensor)
        if snap is None:
            return MetricValue(None, SensorIssue.MISSING)
        if snap.status == "warming_up":
            return MetricValue(None, SensorIssue.WARMING_UP)
        if snap.status == "stale":
            return MetricValue(None, SensorIssue.STALE)
        value = snap.temperature_c if metric == "temperature" else snap.humidity
        return MetricValue(value, None if value is not None else SensorIssue.STALE)

    def history(self, sensor: str, since: int) -> list[dict]:
        with transaction(self._db_path) as conn:
            rows = conn.execute(
                "SELECT created_at, temperature_c, humidity FROM sensor_samples "
                "WHERE sensor = ? AND created_at >= ? AND ok = 1 ORDER BY created_at",
                (sensor, since),
            ).fetchall()
        return [dict(row) for row in rows]
