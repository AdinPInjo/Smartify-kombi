"""Battery forecast: where the state of charge is heading in the next hours.

A deliberately simple model that only uses data the van already has:

* **Load**: the average power the van used over the last 24 hours, worked out
  from the battery power plus what solar and the DC-DC charger delivered.
* **Solar**: the hourly solar radiation forecast (Open-Meteo) scaled to your
  panels. Their size is the highest solar power seen recently, unless set.
* **Capacity**: estimated from the SmartShunt (consumed Ah at the current state
  of charge), unless set.

Hour by hour: ``soc += (solar - load) / capacity``. Not counted: shore power and
driving, which only make it better. So the forecast is on the safe side.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from statistics import fmean
from typing import Any

HOURS = 36
_NOMINAL_VOLTAGE = 12.8
_DEFAULT_CAPACITY_AH = 100.0
_MIN_HISTORY_SAMPLES = 30  # about 30 minutes of one-minute averages
_FULL_SUN_W_M2 = 800.0  # radiation at which van panels reach their real-world peak
_LOW_SOC = 10.0


@dataclass
class Forecast:
    available: bool
    reason: str | None = None
    soc_now: float | None = None
    min_soc: float | None = None
    min_at: int | None = None
    low_at: int | None = None
    """When the battery drops below 10 % (None: not within the forecast)."""
    load_w: float | None = None
    solar_peak_w: float | None = None
    solar_wh_24h: float | None = None
    capacity_ah: float | None = None
    capacity_estimated: bool = False
    points: list[dict[str, float]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def estimate_capacity(soc: float | None, consumed_ah: float | None) -> float | None:
    """Battery size from the shunt: 30 Ah consumed at 70 % means about 100 Ah."""
    if soc is None or consumed_ah is None or soc >= 95 or consumed_ah > -2:
        return None
    capacity = -consumed_ah / (1 - soc / 100)
    return round(capacity) if 20 <= capacity <= 5000 else None


def average_load_w(history: list[dict[str, Any]]) -> float | None:
    """Mean power used by the van, from one-minute energy samples."""
    loads = []
    for row in history:
        voltage, current = row.get("battery_voltage"), row.get("battery_current")
        if voltage is None or current is None:
            continue
        solar = row.get("solar_power") or 0.0
        dcdc = (row.get("dcdc_output_current") or 0.0) * voltage
        loads.append(max(0.0, solar + dcdc - voltage * current))
    if len(loads) < _MIN_HISTORY_SAMPLES:
        return None
    return fmean(loads)


def compute(
    summary: dict[str, Any],
    history: list[dict[str, Any]],
    hourly: list[dict[str, Any]],
    now: float,
    capacity_ah: float | None = None,
    solar_peak_w: float | None = None,
) -> Forecast:
    battery = summary.get("battery") or {}
    soc = battery.get("soc")
    if not summary.get("available") or soc is None:
        return Forecast(False, "needs a battery monitor (SmartShunt) reporting the charge")
    load = average_load_w(history)
    if load is None:
        return Forecast(False, "collecting usage data, ready after about 30 minutes", soc_now=soc)

    estimated = False
    if capacity_ah is None:
        capacity_ah = estimate_capacity(soc, battery.get("consumed_ah"))
        estimated = True
        if capacity_ah is None:
            capacity_ah = _DEFAULT_CAPACITY_AH
    if solar_peak_w is None:
        seen = [row["solar_power"] for row in history if row.get("solar_power") is not None]
        solar_peak_w = max(seen, default=0.0)

    radiation = {int(h["ts"]) // 3600: h.get("radiation_w_m2") for h in hourly}
    voltage = battery.get("voltage") or _NOMINAL_VOLTAGE
    capacity_wh = capacity_ah * max(voltage, 11.0)

    level = float(soc)
    hour = int(now) // 3600
    points = [{"ts": int(now), "soc": round(level, 1)}]
    min_soc, min_at, low_at = level, int(now), None
    solar_24h = 0.0
    for step in range(1, HOURS + 1):
        sun = radiation.get(hour + step - 1) or 0.0
        solar_w = min(solar_peak_w, solar_peak_w * sun / _FULL_SUN_W_M2)
        if step <= 24:
            solar_24h += solar_w
        level = min(100.0, max(0.0, level + (solar_w - load) / capacity_wh * 100))
        ts = (hour + step) * 3600
        points.append({"ts": ts, "soc": round(level, 1)})
        if level < min_soc:
            min_soc, min_at = level, ts
        if low_at is None and level <= _LOW_SOC:
            low_at = ts

    return Forecast(
        available=True,
        soc_now=soc,
        min_soc=round(min_soc, 1),
        min_at=min_at,
        low_at=low_at,
        load_w=round(load, 1),
        solar_peak_w=round(solar_peak_w),
        solar_wh_24h=round(solar_24h),
        capacity_ah=capacity_ah,
        capacity_estimated=estimated,
        points=points,
    )
