"""Keep the most recent log records in memory for the dashboard's log view."""

from __future__ import annotations

import logging
import threading
from collections import deque


class LogBuffer(logging.Handler):
    def __init__(self, capacity: int = 500) -> None:
        super().__init__(level=logging.INFO)
        self._records: deque[dict] = deque(maxlen=capacity)
        self._lock_records = threading.Lock()
        self._next_id = 1

    def set_debug(self, on: bool) -> None:
        """Debug mode: keep debug records too, and more of them."""
        self.setLevel(logging.DEBUG if on else logging.INFO)
        with self._lock_records:
            self._records = deque(self._records, maxlen=3000 if on else 500)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = record.getMessage()
        except Exception:  # never let logging break the app
            message = str(record.msg)
        with self._lock_records:
            self._records.append(
                {
                    "id": self._next_id,
                    "time": int(record.created),
                    "level": record.levelname,
                    "logger": record.name,
                    "message": message,
                }
            )
            self._next_id += 1

    def recent(self, limit: int = 200, min_level: str = "INFO", after_id: int = 0) -> list[dict]:
        threshold = logging.getLevelName(min_level)
        if not isinstance(threshold, int):
            threshold = logging.INFO
        with self._lock_records:
            records = [
                r
                for r in self._records
                if r["id"] > after_id and logging.getLevelName(r["level"]) >= threshold
            ]
        return records[-limit:]
