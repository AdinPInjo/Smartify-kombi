"""Debug mode (Settings → Troubleshooting): detailed logs for a while.

While on, every sensor reading, failed read and Bluetooth exchange is logged and
kept in the dashboard's log view (Logs page). It switches itself off after the
chosen time, so the system journal on the SD card doesn't fill up.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from smartify.db import transaction
from smartify.logbuffer import LogBuffer

log = logging.getLogger(__name__)

KEY = "debug_until"


class DebugMode:
    def __init__(
        self,
        db_path: Path,
        logs: LogBuffer,
        normal_level: str,
        clock: Callable[[], float] = time.time,
    ):
        self._db = db_path
        self._logs = logs
        self._normal = normal_level
        self._clock = clock
        self._applied: bool | None = None

    def _until(self) -> int | None:
        with transaction(self._db) as conn:
            row = conn.execute("SELECT v FROM app_settings WHERE k = ?", (KEY,)).fetchone()
        return int(row["v"]) if row else None

    def state(self) -> dict[str, Any]:
        until = self._until()
        on = until is not None and until > self._clock()
        return {"enabled": on, "until": until if on else None}

    def set(self, enabled: bool, hours: float = 2) -> dict[str, Any]:
        with transaction(self._db) as conn:
            if enabled:
                until = int(self._clock() + hours * 3600)
                conn.execute(
                    "INSERT INTO app_settings (k, v) VALUES (?, ?) "
                    "ON CONFLICT (k) DO UPDATE SET v = excluded.v",
                    (KEY, str(until)),
                )
            else:
                conn.execute("DELETE FROM app_settings WHERE k = ?", (KEY,))
        self.apply()
        return self.state()

    def apply(self) -> None:
        """Set the log level to match; also called every minute to end it on time."""
        on = self.state()["enabled"]
        if on == self._applied:
            return
        first = self._applied is None
        self._applied = on
        logging.getLogger("smartify").setLevel(logging.DEBUG if on else self._normal)
        self._logs.set_debug(on)
        if on or not first:  # nothing to say at start-up when it's simply off
            log.info("Debug mode %s", "on: detailed logs in the Logs page" if on else "off")
