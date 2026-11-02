"""Automation rules: storage and the decision of what an automatic relay should do.

Decision for a relay in ``auto`` mode, rules checked from highest priority down:

1. A rule whose sensor is still warming up: keep the relay as it is.
2. A rule whose sensor is stale or missing: switch the relay off (fail safe;
   a heater must not keep running on a dead sensor).
3. The first rule whose condition matches decides (its ``action``).
4. No rule matches, or no enabled rules: off.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from smartify.db import transaction
from smartify.errors import InvalidInput, NotFound
from smartify.services.conditions import (
    Evaluation,
    MetricSource,
    SensorIssue,
    dump_condition,
    evaluate,
    parse_condition,
    sensors_used,
)

log = logging.getLogger(__name__)

State = Literal["on", "off"]


@dataclass(frozen=True)
class Rule:
    id: str
    relay_id: str
    name: str
    enabled: bool
    priority: int
    condition: dict[str, Any]
    action: State
    cooldown_seconds: int
    last_triggered_at: int | None
    created_at: int
    updated_at: int
    revision: int

    @classmethod
    def from_row(cls, row) -> Rule:
        return cls(
            id=row["id"],
            relay_id=row["relay_id"],
            name=row["name"],
            enabled=bool(row["enabled"]),
            priority=row["priority"],
            condition=json.loads(row["condition_json"]),
            action=row["action"],
            cooldown_seconds=row["cooldown_seconds"],
            last_triggered_at=row["last_triggered_at"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            revision=row["revision"],
        )


@dataclass(frozen=True)
class RuleStatus:
    """How a rule evaluates right now (shown in the dashboard)."""

    rule_id: str
    matched: bool
    issue: SensorIssue | None
    values: dict[str, float]
    is_winner: bool


@dataclass(frozen=True)
class Decision:
    state: State | None
    """Desired state, or ``None`` to keep the current state."""
    reason: str
    rule: Rule | None = None
    """The matching rule, if a rule decided."""
    statuses: tuple[RuleStatus, ...] = ()
    fail_safe: bool = False
    """The relay must go off now for safety (sensor dead, invalid rule, error).
    Switching protection (min on time, cooldown) does not delay it."""


_EDITABLE = {"name", "enabled", "priority", "condition", "action", "cooldown_seconds"}


class RuleService:
    def __init__(
        self,
        db_path: Path,
        metric_source: MetricSource,
        sensor_names: Callable[[], list[str]] = list,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._db_path = db_path
        self._metric_source = metric_source
        self._sensor_names = sensor_names
        self._clock = clock

    @property
    def metric_source(self) -> MetricSource:
        return self._metric_source

    @property
    def sensor_names(self) -> list[str]:
        return list(self._sensor_names())

    def _validated_condition_json(self, condition: Any) -> str:
        parsed = parse_condition(condition)
        unknown = sensors_used(parsed) - set(self._sensor_names())
        if unknown:
            known = ", ".join(self._sensor_names()) or "none configured"
            raise InvalidInput(f"unknown sensor {', '.join(sorted(unknown))} (available: {known})")
        return json.dumps(dump_condition(parsed))

    # --- storage ---------------------------------------------------------

    def list(self, relay_id: str | None = None) -> list[Rule]:
        query = "SELECT * FROM rules"
        params: tuple = ()
        if relay_id is not None:
            query += " WHERE relay_id = ?"
            params = (relay_id,)
        query += " ORDER BY priority DESC, created_at, id"
        with transaction(self._db_path) as conn:
            return [Rule.from_row(row) for row in conn.execute(query, params)]

    def get(self, rule_id: str) -> Rule:
        with transaction(self._db_path) as conn:
            row = conn.execute("SELECT * FROM rules WHERE id = ?", (rule_id,)).fetchone()
        if row is None:
            raise NotFound(f"rule {rule_id} not found")
        return Rule.from_row(row)

    def create(
        self,
        relay_id: str,
        *,
        name: str,
        condition: dict[str, Any],
        action: State,
        priority: int = 100,
        cooldown_seconds: int = 60,
        enabled: bool = True,
    ) -> Rule:
        condition_json = self._validated_condition_json(condition)
        now = int(self._clock())
        rule_id = str(uuid.uuid4())
        with transaction(self._db_path) as conn:
            if conn.execute("SELECT 1 FROM relays WHERE id = ?", (relay_id,)).fetchone() is None:
                raise NotFound(f"relay {relay_id} not found")
            conn.execute(
                "INSERT INTO rules (id, relay_id, name, enabled, priority, condition_json, action, "
                "cooldown_seconds, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    rule_id,
                    relay_id,
                    name,
                    int(enabled),
                    priority,
                    condition_json,
                    action,
                    cooldown_seconds,
                    now,
                    now,
                ),
            )
        return self.get(rule_id)

    def update(self, rule_id: str, changes: dict[str, Any]) -> Rule:
        unknown = set(changes) - _EDITABLE
        if unknown:
            raise InvalidInput(f"cannot change {', '.join(sorted(unknown))}")
        columns: dict[str, Any] = {}
        for key, value in changes.items():
            if key == "condition":
                columns["condition_json"] = self._validated_condition_json(value)
            elif key == "enabled":
                columns["enabled"] = int(value)
            else:
                columns[key] = value
        if not columns:
            return self.get(rule_id)
        assignments = ", ".join(f"{column} = ?" for column in columns)
        with transaction(self._db_path) as conn:
            cursor = conn.execute(
                f"UPDATE rules SET {assignments}, updated_at = ?, revision = revision + 1 "
                "WHERE id = ?",
                (*columns.values(), int(self._clock()), rule_id),
            )
            if cursor.rowcount == 0:
                raise NotFound(f"rule {rule_id} not found")
        return self.get(rule_id)

    def delete(self, rule_id: str) -> Rule:
        rule = self.get(rule_id)
        with transaction(self._db_path) as conn:
            conn.execute("DELETE FROM rules WHERE id = ?", (rule_id,))
        return rule

    def mark_triggered(self, rule_id: str) -> None:
        # Runtime bookkeeping, not a settings change: no revision bump.
        with transaction(self._db_path) as conn:
            conn.execute(
                "UPDATE rules SET last_triggered_at = ? WHERE id = ?",
                (int(self._clock()), rule_id),
            )

    # --- decision --------------------------------------------------------

    def decide(self, relay_id: str) -> Decision:
        """Never raises: any error becomes a fail-safe "off"."""
        try:
            return self._decide(relay_id)
        except Exception as exc:
            log.exception("Rule evaluation for relay %s failed", relay_id)
            return Decision("off", f"rule evaluation failed: {exc}", fail_safe=True)

    def _decide(self, relay_id: str) -> Decision:
        rules = [rule for rule in self.list(relay_id) if rule.enabled]
        if not rules:
            return Decision("off", "no enabled rules")

        evaluations: list[tuple[Rule, Evaluation]] = []
        decision: Decision | None = None
        for rule in rules:
            try:
                result = evaluate(parse_condition(rule.condition), self._metric_source)
            except InvalidInput as exc:
                # A stored rule that no longer validates (manual DB edit, sync).
                result = Evaluation(False, SensorIssue.MISSING)
                if decision is None:
                    decision = Decision(
                        "off", f"rule '{rule.name}' is invalid: {exc}", fail_safe=True
                    )
            evaluations.append((rule, result))
            if decision is not None:
                continue  # keep evaluating so every rule gets a status
            if result.issue is SensorIssue.WARMING_UP:
                decision = Decision(None, f"waiting for sensor data ({rule.name})")
            elif result.issue is not None:
                decision = Decision(
                    "off", f"sensor {result.issue.value} ({rule.name})", fail_safe=True
                )
            elif result.matched:
                decision = Decision(rule.action, f"rule '{rule.name}'", rule)

        if decision is None:
            decision = Decision("off", "no rule matches")
        winner_id = decision.rule.id if decision.rule else None
        statuses = tuple(
            RuleStatus(rule.id, result.matched, result.issue, result.values, rule.id == winner_id)
            for rule, result in evaluations
        )
        return Decision(
            decision.state, decision.reason, decision.rule, statuses, decision.fail_safe
        )
