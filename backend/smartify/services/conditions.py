"""Rule conditions: validation and evaluation.

A condition is a small JSON tree::

    {"type": "threshold", "metric": "temperature", "sensor": "inside", "op": "<", "value": 8}
    {"type": "range", "metric": "humidity", "sensor": "inside", "min": 40, "max": 70}
    {"type": "all", "conditions": [...]}     # every sub-condition matches
    {"type": "any", "conditions": [...]}     # at least one matches
    {"type": "not", "condition": {...}}
    {"type": "always"}

``range`` matches ``min <= value < max``.

Evaluation never raises. When a sensor cannot be trusted the result says why,
so the relay logic can decide what to do (see ``SensorIssue``).
"""

from __future__ import annotations

import enum
import operator
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, TypeAdapter, ValidationError, model_validator

from smartify.errors import InvalidInput

Metric = Literal["temperature", "humidity"]

_OPERATORS: dict[str, Callable[[float, float], bool]] = {
    "<": operator.lt,
    "<=": operator.le,
    ">": operator.gt,
    ">=": operator.ge,
}

_METRIC_LIMITS: dict[str, tuple[float, float]] = {
    "temperature": (-40.0, 80.0),  # DHT22 range
    "humidity": (0.0, 100.0),
}

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


class All(BaseModel):
    type: Literal["all"]
    conditions: list[Condition] = Field(min_length=1, max_length=10)


class Any_(BaseModel):
    type: Literal["any"]
    conditions: list[Condition] = Field(min_length=1, max_length=10)


class Not(BaseModel):
    type: Literal["not"]
    condition: Condition


Condition = Annotated[Threshold | Range | Always | All | Any_ | Not, Field(discriminator="type")]
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
    return _ADAPTER.dump_python(condition, mode="json")


def sensors_used(condition: Condition) -> set[str]:
    if isinstance(condition, Threshold | Range):
        return {condition.sensor}
    if isinstance(condition, All | Any_):
        return set().union(*(sensors_used(c) for c in condition.conditions))
    if isinstance(condition, Not):
        return sensors_used(condition.condition)
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


def evaluate(condition: Condition, source: MetricSource) -> Evaluation:
    if isinstance(condition, Always):
        return Evaluation(True)

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
        inner = evaluate(condition.condition, source)
        if inner.issue is not None:
            return Evaluation(False, inner.issue, inner.values)
        return Evaluation(not inner.matched, values=inner.values)

    # all / any: any sensor issue makes the whole result untrustworthy.
    results = [evaluate(c, source) for c in condition.conditions]
    values: dict[str, float] = {}
    for result in results:
        values.update(result.values)
    issue = _worst(*(r.issue for r in results))
    if issue is not None:
        return Evaluation(False, issue, values)
    combine = all if isinstance(condition, All) else any
    return Evaluation(combine(r.matched for r in results), values=values)
