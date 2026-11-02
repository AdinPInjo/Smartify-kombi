"""Background loops (sensor sampling, rule evaluation, GPS, storage).

Each worker is a daemon thread that calls one function at a fixed interval. An
exception is logged and the loop carries on, so one failing device can never
stop the others (the old code needed a watchdog to restart dead threads).
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class WorkerStatus:
    name: str
    running: bool
    interval_seconds: float
    runs: int
    last_run_at: int | None
    last_error: str | None
    last_error_at: int | None


class Worker:
    def __init__(self, name: str, interval_seconds: float, task: Callable[[], None]) -> None:
        self.name = name
        self.interval = interval_seconds
        self._task = task
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._runs = 0
        self._last_run_at: float | None = None
        self._last_error: str | None = None
        self._last_error_at: float | None = None
        self._repeated_errors = 0

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, name=f"worker-{self.name}", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout)

    def _loop(self) -> None:
        while not self._stop.is_set():
            started = time.monotonic()
            try:
                self._task()
                self._repeated_errors = 0
            except Exception as exc:
                self._last_error = f"{type(exc).__name__}: {exc}"
                self._last_error_at = time.time()
                self._repeated_errors += 1
                # Log the full traceback once, then only every 100th repeat.
                if self._repeated_errors == 1 or self._repeated_errors % 100 == 0:
                    log.exception(
                        "Worker %s failed (%d times in a row)", self.name, self._repeated_errors
                    )
            self._runs += 1
            self._last_run_at = time.time()
            elapsed = time.monotonic() - started
            self._stop.wait(max(0.0, self.interval - elapsed))

    def status(self) -> WorkerStatus:
        return WorkerStatus(
            name=self.name,
            running=self._thread is not None and self._thread.is_alive(),
            interval_seconds=self.interval,
            runs=self._runs,
            last_run_at=int(self._last_run_at) if self._last_run_at else None,
            last_error=self._last_error,
            last_error_at=int(self._last_error_at) if self._last_error_at else None,
        )
