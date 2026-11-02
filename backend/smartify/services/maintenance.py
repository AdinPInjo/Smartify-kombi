"""Housekeeping: history retention, database health check and backups."""

from __future__ import annotations

import logging
import sqlite3
import time
from pathlib import Path

from smartify.db import connect, transaction
from smartify.services.gps_archive import archive_points

log = logging.getLogger(__name__)

_HISTORY_TABLES = (
    "sensor_samples",
    "water_level_samples",
    "gps_fixes",
    "weather_samples",
    "energy_samples",
    "relay_events",
)
BACKUPS_KEPT = 3


def prune_history(db_path: Path, retention_days: int, now: float | None = None) -> int:
    """Delete history older than ``retention_days``. Returns the number of rows deleted.

    GPS points are first written to the monthly GPX archive (see gps_archive).

    The Pi has no real-time clock. If the clock is far ahead of the newest stored
    data (wrong time after boot), nothing is deleted rather than everything.
    """
    now = now if now is not None else time.time()
    retention = retention_days * 86400
    with transaction(db_path) as conn:
        newest = conn.execute("SELECT MAX(created_at) FROM sensor_samples").fetchone()[0]
        if newest is not None and now - newest > retention:
            log.warning("Clock looks wrong (newest data is older than retention); not pruning")
            return 0
        cutoff = int(now - retention)
        deleted = 0
        old_points = conn.execute(
            "SELECT lat, lon, altitude_m, created_at FROM gps_fixes WHERE created_at < ? "
            "ORDER BY created_at",
            (cutoff,),
        ).fetchall()
        if old_points:
            # Archive first; if that fails the exception aborts the whole prune,
            # so no GPS point is deleted without being in the archive.
            archive_points(db_path.parent, [tuple(row) for row in old_points])
        for table in _HISTORY_TABLES:
            deleted += conn.execute(f"DELETE FROM {table} WHERE created_at < ?", (cutoff,)).rowcount
        # gps_distance_daily is kept forever: one tiny row per day, and it holds
        # the van's total distance.
    if deleted:
        log.info("Deleted %d history rows older than %d days", deleted, retention_days)
    return deleted


def check_integrity(db_path: Path) -> bool:
    """Quick structural check, run at startup. Power cuts are common in a van."""
    conn = connect(db_path)
    try:
        result = conn.execute("PRAGMA quick_check").fetchone()[0]
    finally:
        conn.close()
    if result != "ok":
        log.error(
            "Database integrity check failed: %s. Restore a file from %s",
            result,
            db_path.parent / "backups",
        )
        return False
    return True


def backup(db_path: Path, now: float | None = None) -> Path | None:
    """Write a consistent copy to ``data/backups`` once a day; keep the last few.

    This protects against a corrupted database (e.g. power cut during a write),
    not against a dead SD card; copy the backups off the Pi for that.
    """
    stamp = time.strftime("%Y-%m-%d", time.localtime(now if now is not None else time.time()))
    folder = db_path.parent / "backups"
    target = folder / f"{db_path.stem}-{stamp}.db"
    if target.exists():
        return None
    folder.mkdir(parents=True, exist_ok=True)
    source = connect(db_path)
    try:
        dest = sqlite3.connect(target)
        try:
            source.backup(dest)
        finally:
            dest.close()
    finally:
        source.close()
    for old in sorted(folder.glob(f"{db_path.stem}-*.db"))[:-BACKUPS_KEPT]:
        old.unlink()
    log.info("Database backed up to %s", target)
    return target
