"""
Watchdog service to monitor background threads and restart if stalled.
"""
import threading
import time
from typing import Callable, Dict, Tuple

from smartify import state


_REGISTRY: Dict[str, Tuple[Callable[[], None], int]] = {}


def register_thread(name: str, start_func: Callable[[], None], timeout_seconds: int) -> None:
    _REGISTRY[name] = (start_func, timeout_seconds)


def _mark(name: str, status: str, error: str | None = None) -> None:
    state._thread_health[name] = {
        "last_heartbeat": int(time.time()),
        "status": status,
        "error": error,
    }


def _watchdog_loop() -> None:
    while True:
        now = int(time.time())
        for name, (start_func, timeout_seconds) in _REGISTRY.items():
            info = state._thread_health.get(name, {})
            last = info.get("last_heartbeat") or 0
            if last == 0:
                continue
            if (now - last) > timeout_seconds:
                print(f"[Watchdog] Thread '{name}' stale ({now - last}s). Restarting...")
                _mark(name, "restarting", "stale_heartbeat")
                try:
                    start_func()
                    _mark(name, "ok", None)
                except Exception as e:
                    _mark(name, "error", f"restart_failed: {e}")
        time.sleep(10)


def start_watchdog_thread() -> None:
    t = threading.Thread(target=_watchdog_loop, daemon=True, name="WatchdogThread")
    t.start()
    print("[Watchdog] Thread started")
