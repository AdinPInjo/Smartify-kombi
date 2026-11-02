"""Energy data from Victron devices: battery, solar, DC-DC charger, inverter/charger.

Each device's latest reading is kept in memory and goes stale after
``victron_stale_seconds`` without an advertisement. A summary combines them in
order of trust: the battery monitor (SmartShunt) is the authority for battery
values; without it the inverter/charger or the solar charger fill in.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from statistics import fmean
from typing import Any

from smartify.db import transaction
from smartify.hardware import VictronReading
from smartify.services.conditions import MetricValue, SensorIssue

# Rule metric -> value names to look for, per device kind, in order of preference.
_METRIC_FIELDS: dict[str, dict[str, str]] = {
    "battery_soc": {"battery_monitor": "soc", "inverter_charger": "soc"},
    "battery_voltage": {
        "battery_monitor": "voltage",
        "inverter_charger": "battery_voltage",
        "solar_charger": "battery_voltage",
    },
    "battery_current": {"battery_monitor": "current", "inverter_charger": "battery_current"},
    "solar_power": {"solar_charger": "solar_power"},
}
ENERGY_METRICS = tuple(_METRIC_FIELDS)

# Summary column -> (device kind, value name), first available wins.
_SUMMARY_SOURCES: dict[str, list[tuple[str, str]]] = {
    "battery_voltage": [
        ("battery_monitor", "voltage"),
        ("inverter_charger", "battery_voltage"),
        ("solar_charger", "battery_voltage"),
    ],
    "battery_current": [("battery_monitor", "current"), ("inverter_charger", "battery_current")],
    "battery_soc": [("battery_monitor", "soc"), ("inverter_charger", "soc")],
    "solar_power": [("solar_charger", "solar_power")],
    "solar_yield_today": [("solar_charger", "yield_today")],
    "dcdc_output_current": [("dcdc_converter", "output_current")],
    "ac_out_power": [("inverter_charger", "ac_out_power")],
}


@dataclass(frozen=True)
class DeviceState:
    device: str
    kind: str
    model: str | None
    values: dict[str, Any]
    rssi: int | None
    updated_at: int
    stale: bool


class EnergyService:
    def __init__(
        self,
        db_path: Path,
        stale_seconds: int = 120,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._db_path = db_path
        self._stale_seconds = stale_seconds
        self._clock = clock
        self._lock = threading.Lock()
        self._latest: dict[str, tuple[VictronReading, float]] = {}
        self._minute: dict[str, list[float]] = {}
        self._started_at = clock()

    def on_reading(self, reading: VictronReading) -> None:
        """Called by the Victron listener for every decoded advertisement."""
        now = self._clock()
        with self._lock:
            self._latest[reading.device] = (reading, now)
            for column, value in self._summary_values().items():
                if isinstance(value, int | float):
                    self._minute.setdefault(column, []).append(float(value))

    # --- queries ---------------------------------------------------------

    def devices(self) -> list[DeviceState]:
        now = self._clock()
        with self._lock:
            items = sorted(self._latest.values(), key=lambda item: item[0].device)
        return [
            DeviceState(
                device=r.device,
                kind=r.kind,
                model=r.model,
                values=dict(r.values),
                rssi=r.rssi,
                updated_at=int(at),
                stale=now - at > self._stale_seconds,
            )
            for r, at in items
        ]

    def device_names(self) -> list[str]:
        with self._lock:
            return sorted(self._latest)

    def _fresh_by_kind(self) -> dict[str, VictronReading]:
        """Freshest non-stale reading per device kind. Caller holds the lock."""
        now = self._clock()
        result: dict[str, tuple[VictronReading, float]] = {}
        for reading, at in self._latest.values():
            if now - at > self._stale_seconds:
                continue
            if reading.kind not in result or at > result[reading.kind][1]:
                result[reading.kind] = (reading, at)
        return {kind: item[0] for kind, item in result.items()}

    def _summary_values(self) -> dict[str, Any]:
        by_kind = self._fresh_by_kind()
        values: dict[str, Any] = {}
        for column, sources in _SUMMARY_SOURCES.items():
            values[column] = None
            for kind, field in sources:
                value = by_kind.get(kind) and by_kind[kind].values.get(field)
                if value is not None:
                    values[column] = value
                    break
        return values

    def summary(self) -> dict[str, Any]:
        with self._lock:
            values = self._summary_values()
            by_kind = self._fresh_by_kind()
        voltage, current = values["battery_voltage"], values["battery_current"]
        shunt = by_kind.get("battery_monitor")
        solar = by_kind.get("solar_charger")
        dcdc = by_kind.get("dcdc_converter")
        inverter = by_kind.get("inverter_charger")
        return {
            "available": bool(by_kind),
            "battery": {
                "voltage": voltage,
                "current": current,
                "power": round(voltage * current) if voltage and current is not None else None,
                "soc": values["battery_soc"],
                "remaining_mins": shunt.values.get("remaining_mins") if shunt else None,
                "consumed_ah": shunt.values.get("consumed_ah") if shunt else None,
                "starter_voltage": shunt.values.get("starter_voltage") if shunt else None,
                "alarm": shunt.values.get("alarm") if shunt else None,
            },
            "solar": {
                "power": values["solar_power"],
                "yield_today_wh": values["solar_yield_today"],
                "charge_state": solar.values.get("charge_state") if solar else None,
                "error": solar.values.get("charger_error") if solar else None,
            }
            if solar
            else None,
            "dcdc": {
                "charge_state": dcdc.values.get("charge_state"),
                "input_voltage": dcdc.values.get("input_voltage"),
                "output_voltage": dcdc.values.get("output_voltage"),
                "output_current": dcdc.values.get("output_current"),
                "off_reason": dcdc.values.get("off_reason"),
            }
            if dcdc
            else None,
            "inverter": {
                "state": inverter.values.get("device_state"),
                "ac_in_state": inverter.values.get("ac_in_state"),
                "ac_in_power": inverter.values.get("ac_in_power"),
                "ac_out_power": inverter.values.get("ac_out_power"),
                "alarm": inverter.values.get("alarm"),
            }
            if inverter
            else None,
        }

    def metric(self, device: str, metric: str) -> MetricValue:
        """Value source for rule conditions on energy metrics."""
        now = self._clock()
        with self._lock:
            item = self._latest.get(device)
        if item is None:
            # Not heard from yet: give Bluetooth time after startup.
            if now - self._started_at < self._stale_seconds:
                return MetricValue(None, SensorIssue.WARMING_UP)
            return MetricValue(None, SensorIssue.MISSING)
        reading, at = item
        if now - at > self._stale_seconds:
            return MetricValue(None, SensorIssue.STALE)
        field = _METRIC_FIELDS.get(metric, {}).get(reading.kind)
        value = reading.values.get(field) if field else None
        if not isinstance(value, int | float):
            return MetricValue(None, SensorIssue.MISSING)
        return MetricValue(float(value))

    def devices_for(self, metric: str) -> list[str]:
        kinds = set(_METRIC_FIELDS.get(metric, {}))
        with self._lock:
            return sorted(name for name, (r, _) in self._latest.items() if r.kind in kinds)

    # --- history ---------------------------------------------------------

    def flush_minute(self) -> None:
        with self._lock:
            minute, self._minute = self._minute, {}
        if not minute:
            return
        row = {column: round(fmean(values), 3) for column, values in minute.items() if values}
        if "solar_yield_today" in minute:  # a running total, not an average
            row["solar_yield_today"] = minute["solar_yield_today"][-1]
        columns = list(_SUMMARY_SOURCES)
        with transaction(self._db_path) as conn:
            conn.execute(
                f"INSERT INTO energy_samples ({', '.join(columns)}, created_at) "
                f"VALUES ({', '.join('?' * (len(columns) + 1))})",
                (*(row.get(c) for c in columns), int(self._clock())),
            )

    def history(self, since: int) -> list[dict]:
        with transaction(self._db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM energy_samples WHERE created_at >= ? ORDER BY created_at",
                (since,),
            ).fetchall()
        return [{k: row[k] for k in row.keys() if k != "id"} for row in rows]
