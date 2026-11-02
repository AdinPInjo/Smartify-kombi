"""Housekeeping: delete history older than ``retention_days``."""

from __future__ import annotations

import logging
import time
from pathlib import Path

from smartify.db import transaction

log = logging.getLogger(__name__)

_HISTORY_TABLES = (
    "sensor_samples",
    "water_level_samples",
    "gps_fixes",
    "weather_samples",
    "relay_events",
)


def prune_history(db_path: Path, retention_days: int, now: float | None = None) -> int:
    cutoff = int((now if now is not None else time.time()) - retention_days * 86400)
    deleted = 0
    with transaction(db_path) as conn:
        for table in _HISTORY_TABLES:
            deleted += conn.execute(f"DELETE FROM {table} WHERE created_at < ?", (cutoff,)).rowcount
        # gps_distance_daily is kept forever: one tiny row per day, and it holds
        # the van's total distance.
    if deleted:
        log.info("Deleted %d history rows older than %d days", deleted, retention_days)
    return deleted
