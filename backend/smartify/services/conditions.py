"""Rule conditions: validation and evaluation.

A condition is a small JSON tree::

    {"type": "threshold", "metric": "temperature", "sensor": "inside", "op": "<", "value": 8}
    {"type": "range", "metric": "humidity", "sensor": "inside", "min": 40, "max": 70}
    {"type": "all", "conditions": [...]}     # every sub-condition matches
    {"type": "any", "conditions": [...]}     # at least one matches
    {"type": "not", "condition": {...}}
    {"type": "always"}
    {"type": "time", "from": "06:30", "to": "08:00", "days": [0, 1, 2, 3, 4]}

``range`` matches ``min <= value < max``. ``time`` matches local time
``from <= now < to`` (a window past midnight such as 22:00-07:00 works too);
``days`` is optional, 0 = Monday. Only on the days listed does the window start.

Evaluation never raises. When a sensor cannot be trusted the result says why,
so the relay logic can decide what to do (see ``SensorIssue``).
"""

from __future__ import annotations

import enum
import operator
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, TypeAdapter, ValidationError, model_validator

from smartify.errors import InvalidInput

Metric = Literal[
    # DHT22 sensors (sensor = sensor name)
    "temperature",
    "humidity",
    # Victron devices (sensor = device name)
    "battery_soc",
    "battery_voltage",
    "battery_current",
    "solar_power",
    # Water tank (sensor = "tank")
    "water_level",
    # GPS speed in km/h, 0 while parked (sensor = "gps")
    "speed",
]
CLIMATE_METRICS = ("temperature", "humidity")
WATER_SENSOR = "tank"
GPS_SENSOR = "gps"

_OPERATORS: dict[str, Callable[[float, float], bool]] = {
    "<": operator.lt,
    "<=": operator.le,
    ">": operator.gt,
    ">=": operator.ge,
}

_METRIC_LIMITS: dict[str, tuple[float, float]] = {
    "temperature": (-40.0, 80.0),  # DHT22 range
    "humidity": (0.0, 100.0),
    "battery_soc": (0.0, 100.0),
    "battery_voltage": (0.0, 70.0),
    "battery_current": (-1000.0, 1000.0),
    "solar_power": (0.0, 10000.0),
    "water_level": (0.0, 100.0),
    "speed": (0.0, 250.0),
}

_CLOCK = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")

MAX_DEPTH = 4


class _Leaf(BaseModel):
    metric: Metric
    sensor: str = Field(min_length=1, max_length=32)


class Threshold(_Leaf):
    type: Literal["threshold"]
    op: Literal["<", "<=", ">", ">="]
    value: float

    @model_validator(mode="after")
    def _in_range(self) -> Threshold:
        low, high = _METRIC_LIMITS[self.metric]
        if not low <= self.value <= high:
            raise ValueError(f"{self.metric} value must be between {low} and {high}")
        return self


class Range(_Leaf):
    type: Literal["range"]
    min: float
    max: float

    @model_validator(mode="after")
    def _ordered(self) -> Range:
        if self.min >= self.max:
            raise ValueError("min must be lower than max")
        low, high = _METRIC_LIMITS[self.metric]
        if self.min < low or self.max > high:
            raise ValueError(f"{self.metric} range must stay within {low}..{high}")
        return self


class Always(BaseModel):
    type: Literal["always"]


class TimeWindow(BaseModel):
    type: Literal["time"]
    from_: str = Field(alias="from")
    to: str
    days: list[int] | None = Field(default=None, min_length=1, max_length=7)

    model_config = {"populate_by_name": True}

    @model_validator(mode="after")
    def _valid(self) -> TimeWindow:
        for value in (self.from_, self.to):
            if not _CLOCK.match(value):
                raise ValueError(f"time {value!r} must look like HH:MM (00:00-23:59)")
        if self.from_ == self.to:
            raise ValueError("from and to must differ")
        if self.days is not None:
            if any(d < 0 or d > 6 for d in self.days):
                raise ValueError("days are 0 (Monday) to 6 (Sunday)")
            self.days = sorted(set(self.days))
        return self

    def matches(self, now: datetime) -> bool:
        minute = now.hour * 60 + now.minute
        start, end = _minutes(self.from_), _minutes(self.to)
        if start < end:
            inside, start_day = start <= minute < end, now.weekday()
        else:  # past midnight: after the start today, or before the end (started yesterday)
            inside = minute >= start or minute < end
            start_day = now.weekday() if minute >= start else (now.weekday() - 1) % 7
        return inside and (self.days is None or start_day in self.days)


def _minutes(clock: str) -> int:
    hours, minutes = clock.split(":")
    return int(hours) * 60 + int(minutes)


class All(BaseModel):
    type: Literal["all"]
    conditions: list[Condition] = Field(min_length=1, max_length=10)


class Any_(BaseModel):
    type: Literal["any"]
    conditions: list[Condition] = Field(min_length=1, max_length=10)


class Not(BaseModel):
    type: Literal["not"]
    condition: Condition


Condition = Annotated[
    Threshold | Range | Always | TimeWindow | All | Any_ | Not, Field(discriminator="type")
]
for _model in (All, Any_, Not):
    _model.model_rebuild()

_ADAPTER: TypeAdapter[Condition] = TypeAdapter(Condition)


def _readable(error: ValidationError) -> str:
    parts = []
    for item in error.errors():
        location = ".".join(str(p) for p in item["loc"] if not isinstance(p, int))
        message = item["msg"].removeprefix("Value error, ")
        parts.append(f"{location}: {message}" if location else message)
    return "invalid condition: " + "; ".join(parts)


def parse_condition(data: Any) -> Condition:
    """Validate a condition. Raises ``InvalidInput`` with a readable message."""
    try:
        condition = _ADAPTER.validate_python(data)
    except ValidationError as exc:
        raise InvalidInput(_readable(exc)) from None
    if _depth(condition) > MAX_DEPTH:
        raise InvalidInput(f"conditions can be nested at most {MAX_DEPTH} levels deep")
    return condition


def dump_condition(condition: Condition) -> dict[str, Any]:
    return _ADAPTER.dump_python(condition, mode="json", by_alias=True, exclude_none=True)


def leaves(condition: Condition) -> set[tuple[str, str]]:
    """Every ``(sensor, metric)`` the condition reads."""
    if isinstance(condition, Threshold | Range):
        return {(condition.sensor, condition.metric)}
    if isinstance(condition, All | Any_):
        return set().union(*(leaves(c) for c in condition.conditions))
    if isinstance(condition, Not):
        return leaves(condition.condition)
    return set()


def _depth(condition: Condition) -> int:
    if isinstance(condition, All | Any_):
        return 1 + max(_depth(c) for c in condition.conditions)
    if isinstance(condition, Not):
        return 1 + _depth(condition.condition)
    return 1


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------


class SensorIssue(enum.StrEnum):
    """Why a sensor value could not be used. Ordered from least to most severe."""

    WARMING_UP = "warming_up"
    """Not enough readings yet since start. Keep the relay as it is."""

    STALE = "stale"
    """No good reading for too long. Fail safe: the relay is switched off."""

    MISSING = "missing"
    """The sensor does not exist (renamed or removed). Fail safe: off."""

    @property
    def severity(self) -> int:
        return list(SensorIssue).index(self)


@dataclass(frozen=True)
class MetricValue:
    value: float | None
    issue: SensorIssue | None = None


MetricSource = Callable[[str, str], MetricValue]
"""``(sensor, metric) -> MetricValue``"""


@dataclass
class Evaluation:
    matched: bool
    issue: SensorIssue | None = None
    values: dict[str, float] = field(default_factory=dict)
    """``"sensor.metric" -> value`` for every reading the condition looked at."""


def _worst(*issues: SensorIssue | None) -> SensorIssue | None:
    present = [i for i in issues if i is not None]
    return max(present, key=lambda i: i.severity) if present else None


def evaluate(condition: Condition, source: MetricSource, now: datetime | None = None) -> Evaluation:
    """``now`` is the local time for ``time`` conditions (default: the system clock)."""
    if isinstance(condition, Always):
        return Evaluation(True)

    if isinstance(condition, TimeWindow):
        return Evaluation(condition.matches(now or datetime.now()))

    if isinstance(condition, Threshold | Range):
        reading = source(condition.sensor, condition.metric)
        if reading.issue is not None or reading.value is None:
            return Evaluation(False, reading.issue or SensorIssue.STALE)
        value = reading.value
        if isinstance(condition, Threshold):
            matched = _OPERATORS[condition.op](value, condition.value)
        else:
            matched = condition.min <= value < condition.max
        return Evaluation(matched, values={f"{condition.sensor}.{condition.metric}": value})

    if isinstance(condition, Not):
        inner = evaluate(condition.condition, source, now)
        if inner.issue is not None:
            return Evaluation(False, inner.issue, inner.values)
        return Evaluation(not inner.matched, values=inner.values)

    # all / any: any sensor issue makes the whole result untrustworthy.
    results = [evaluate(c, source, now) for c in condition.conditions]
    values: dict[str, float] = {}
    for result in results:
        values.update(result.values)
    issue = _worst(*(r.issue for r in results))
    if issue is not None:
        return Evaluation(False, issue, values)
    combine = all if isinstance(condition, All) else any
    return Evaluation(combine(r.matched for r in results), values=values)
