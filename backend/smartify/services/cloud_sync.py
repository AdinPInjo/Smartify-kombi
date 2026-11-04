"""Sync with the remote dashboard (cloud/, PHP + MySQL on any shared hosting).

The Pi always starts the conversation, so it works behind mobile-network NAT
and shared hosting needs nothing but PHP. Every ``cloud_interval_seconds`` it
POSTs to ``<cloud_url>/api/device/sync`` and gets back the commands queued in
the remote dashboard. Every ``cloud_state_seconds`` (or right after applying a
command) the request also carries the live state and new history rows.

The Pi stays the single source of truth. Remote changes are *commands* that go
through the same validation as local ones:

* Switching a relay (manual on/off, back to auto) is applied as long as it is
  delivered within the cloud's command lifetime (15 min by default); an old
  "heater on" never fires hours later.
* Settings changes (relay settings, rules, water calibration) carry the
  revision the remote dashboard was looking at. If that setting changed on the
  van since, the command is rejected: the most recent change made on the van
  wins, and the remote dashboard shows why.
"""

from __future__ import annotations

import gzip
import json
import logging
import time
import urllib.error
import urllib.request
import zlib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from smartify import __version__
from smartify.db import transaction
from smartify.errors import Conflict, DeviceUnavailable, InvalidInput, NotFound

log = logging.getLogger(__name__)

PROTOCOL = 1
HISTORY_BATCH = 500

# SQLite table -> columns uploaded (always with `id`).
HISTORY_TABLES: dict[str, tuple[str, ...]] = {
    "sensor_samples": ("sensor", "temperature_c", "humidity", "ok", "created_at"),
    "water_level_samples": ("level_percent", "battery_voltage", "ok", "created_at"),
    "energy_samples": (
        "battery_voltage",
        "battery_current",
        "battery_soc",
        "solar_power",
        "solar_yield_today",
        "dcdc_output_current",
        "ac_out_power",
        "created_at",
    ),
    "gps_fixes": ("lat", "lon", "speed_kmh", "altitude_m", "created_at"),
    "relay_events": ("relay_id", "source", "old_state", "new_state", "reason", "created_at"),
}

Transport = Callable[[str, dict[str, Any], str], dict[str, Any]]


class CloudError(RuntimeError):
    pass


def http_transport(url: str, body: dict[str, Any], token: str) -> dict[str, Any]:
    data = gzip.compress(json.dumps(body, separators=(",", ":")).encode())
    request = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Content-Encoding": "gzip",
            "Authorization": f"Bearer {token}",
            "User-Agent": f"smartify-kombi/{__version__}",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        detail = exc.read(300).decode(errors="replace")
        raise CloudError(f"HTTP {exc.code}: {detail}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise CloudError(f"cloud unreachable: {getattr(exc, 'reason', exc)}") from exc


@dataclass
class CloudStatus:
    enabled: bool
    url: str
    last_ok_at: int | None = None
    last_error: str | None = None
    last_error_at: int | None = None
    commands_applied: int = 0
    remote_version: str | None = None
    """Version of the remote dashboard, from its last answer."""


class CloudSync:
    def __init__(
        self,
        *,
        url: str,
        token: str,
        db_path: Path,
        state_seconds: float,
        build_state: Callable[[], dict[str, Any]],
        apply_command: Callable[[dict[str, Any]], None],
        transport: Transport = http_transport,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._endpoint = url.rstrip("/") + "/api/device/sync"
        self._token = token
        self._db_path = db_path
        self._state_seconds = state_seconds
        self._build_state = build_state
        self._apply_command = apply_command
        self._transport = transport
        self._clock = clock
        self._next_full = 0.0
        self._results: list[dict[str, Any]] = []
        self.status = CloudStatus(enabled=True, url=url)

    # --- cursors -------------------------------------------------------------

    def _cursor(self, name: str) -> int:
        with transaction(self._db_path) as conn:
            row = conn.execute("SELECT value FROM sync_cursors WHERE name = ?", (name,)).fetchone()
        return row["value"] if row else 0

    def _set_cursor(self, name: str, value: int) -> None:
        with transaction(self._db_path) as conn:
            conn.execute(
                "INSERT INTO sync_cursors (name, value) VALUES (?, ?) "
                "ON CONFLICT (name) DO UPDATE SET value = excluded.value",
                (name, value),
            )

    def reset_cursors(self) -> None:
        """Start over: send all history again and take commands from the first one.

        Needed when the van talks to a different (or reinstalled) cloud, whose
        command numbers start again at 1.
        """
        with transaction(self._db_path) as conn:
            conn.execute("DELETE FROM sync_cursors")
        self._results = []
        self._next_full = 0.0

    def _same_instance(self, response: dict[str, Any]) -> bool:
        """False (and cursors reset) when the cloud is a different installation."""
        instance = response.get("instance")
        if not isinstance(instance, str) or not instance:
            return True  # older cloud without an id
        marker = zlib.crc32(instance.encode()) or 1
        known = self._cursor("instance")
        if known == marker:
            return True
        with transaction(self._db_path) as conn:
            progress = conn.execute(
                "SELECT COUNT(*) FROM sync_cursors WHERE value != 0"
            ).fetchone()[0]
        if known:
            log.info("Remote dashboard was reinstalled or replaced: syncing everything again")
        self.reset_cursors()
        self._set_cursor("instance", marker)
        # Nothing synced before (first connection): this answer is fine to use.
        return progress == 0

    def _history(self) -> dict[str, list[dict[str, Any]]]:
        batches: dict[str, list[dict[str, Any]]] = {}
        with transaction(self._db_path) as conn:
            for table, columns in HISTORY_TABLES.items():
                after = conn.execute(
                    "SELECT value FROM sync_cursors WHERE name = ?", (f"history:{table}",)
                ).fetchone()
                rows = conn.execute(
                    f"SELECT id, {', '.join(columns)} FROM {table} WHERE id > ? "
                    f"ORDER BY id LIMIT {HISTORY_BATCH}",
                    (after["value"] if after else 0,),
                ).fetchall()
                if rows:
                    batches[table] = [dict(row) for row in rows]
        return batches

    # --- one exchange --------------------------------------------------------

    def tick(self) -> None:
        now = self._clock()
        full = now >= self._next_full
        body: dict[str, Any] = {
            "protocol": PROTOCOL,
            "device_time": int(now),
            "last_command_id": self._cursor("last_command_id"),
            "results": list(self._results),
        }
        if full:
            body["state"] = self._build_state()
            body["history"] = self._history()

        try:
            response = self._transport(self._endpoint, body, self._token)
        except Exception as exc:
            self.status.last_error = str(exc)
            self.status.last_error_at = int(now)
            raise

        self._results = []  # delivered
        self.status.last_ok_at = int(now)
        self.status.last_error = None
        if isinstance(response.get("version"), str):
            self.status.remote_version = response["version"][:20]
        if not self._same_instance(response):
            # Our cursors belonged to another cloud: ignore this answer, start fresh next tick.
            self._next_full = now
            return
        if full:
            self._next_full = now + self._state_seconds
        for table, last_id in (response.get("accepted") or {}).items():
            if table in HISTORY_TABLES and isinstance(last_id, int):
                self._set_cursor(f"history:{table}", last_id)
        if full and any(len(rows) >= HISTORY_BATCH for rows in body.get("history", {}).values()):
            self._next_full = now  # more history waiting: continue next tick

        applied = False
        last_id = body["last_command_id"]
        for command in sorted(response.get("commands") or [], key=lambda c: c["id"]):
            if command["id"] <= last_id:
                continue  # already applied; the cloud resent it before our result arrived
            self._results.append(self._run(command))
            last_id = command["id"]
            self._set_cursor("last_command_id", last_id)
            applied = True
        if applied:
            self._next_full = now  # report the new state right away

    def _run(self, command: dict[str, Any]) -> dict[str, Any]:
        result = {"id": command["id"], "ok": False, "status": "failed", "error": None}
        try:
            self._apply_command(command)
        except Conflict as exc:
            result.update(status="rejected", error=str(exc))
        except (InvalidInput, NotFound, DeviceUnavailable) as exc:
            result["error"] = str(exc)
        except Exception as exc:  # never let one command break syncing
            log.exception("Cloud command %s failed", command.get("type"))
            result["error"] = f"{type(exc).__name__}: {exc}"
        else:
            result.update(ok=True, status="done")
            self.status.commands_applied += 1
        log.info(
            "Cloud command %s %s on %s: %s",
            command["id"],
            command.get("type"),
            command.get("target"),
            result["error"] or "applied",
        )
        return result


# --- applying commands -------------------------------------------------------------


def apply_command(ctx: Any, command: dict[str, Any]) -> None:
    """Carry out one remote command through the normal services."""
    kind = command.get("type")
    target = command.get("target")
    payload = command.get("payload") or {}
    base = command.get("base_revision")

    def check_revision(current: int, what: str) -> None:
        if base is not None and current != base:
            raise Conflict(f"{what} was changed on the van in the meantime; the van's change wins")

    if kind == "relay_manual":
        ctx.relays.set_manual(
            target,
            payload["state"],
            (payload.get("duration_minutes") or 0) * 60 or None,
            source="remote",
        )
    elif kind == "relay_auto":
        ctx.relays.set_auto(target)
    elif kind == "scene_run":
        ctx.scenes.run(int(target), source="remote")
    elif kind == "heater_power":
        ctx.heaters.power(target, bool(payload.get("on")), source="remote")
    elif kind == "heater_settings":
        ctx.heaters.settings(
            target, payload.get("mode"), payload.get("temperature"), payload.get("level")
        )
    elif kind == "relay_update":
        check_revision(ctx.relays.get(target).revision, "This relay")
        ctx.relays.update(target, payload)
    elif kind == "rule_create":
        rule = ctx.rules.create(target, **payload)
        ctx.relays.reconcile(rule.relay_id, force=True)
    elif kind == "rule_update":
        check_revision(ctx.rules.get(target).revision, "This rule")
        rule = ctx.rules.update(target, payload)
        ctx.relays.reconcile(rule.relay_id, force=True)
    elif kind == "rule_delete":
        check_revision(ctx.rules.get(target).revision, "This rule")
        rule = ctx.rules.delete(target)
        ctx.relays.reconcile(rule.relay_id, force=True)
    elif kind == "water_settings":
        check_revision(ctx.water.settings().revision, "The water calibration")
        ctx.water.update_settings(payload)
    else:
        raise InvalidInput(f"unknown command type {kind!r}")
