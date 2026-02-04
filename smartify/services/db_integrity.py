"""
Background DB integrity checker with periodic backups.
"""
import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Optional

from smartify import state
from smartify.logging_setup import logger, log_exception
from smartify.config import DB_PATH, DATA_DIR


_STATUS_PATH = Path(DATA_DIR) / "db_integrity_status.json"
_BACKUP_DIR = Path(DATA_DIR) / "backups"
_INTERVAL_SECONDS = 6 * 3600
_KEEP_BACKUPS = 7


def _write_status(payload: dict) -> None:
    try:
        _STATUS_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except Exception:
        log_exception(logger, "[DB Integrity] Failed to write status file", path=str(_STATUS_PATH))


def _backup_db(dest_path: Path) -> Optional[str]:
    try:
        _BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        src = sqlite3.connect(DB_PATH, timeout=10.0)
        dest = sqlite3.connect(str(dest_path))
        with dest:
            src.backup(dest)
        dest.close()
        src.close()
        return None
    except Exception as e:
        log_exception(logger, "[DB Integrity] Backup failed", error=str(e))
        return str(e)


def _prune_backups() -> None:
    try:
        backups = sorted(_BACKUP_DIR.glob("smartify.db.backup.*"), key=lambda p: p.stat().st_mtime, reverse=True)
        for old in backups[_KEEP_BACKUPS:]:
            try:
                old.unlink()
            except Exception:
                pass
    except Exception as e:
        log_exception(logger, "[DB Integrity] Prune backups failed", error=str(e))


def _integrity_check() -> tuple[str, str]:
    try:
        conn = sqlite3.connect(DB_PATH, timeout=10.0)
        cur = conn.cursor()
        cur.execute("PRAGMA integrity_check;")
        rows = cur.fetchall()
        conn.close()
        result = "\n".join(r[0] for r in rows if r and r[0])
        if result.strip() == "ok":
            return ("ok", "ok")
        return ("error", result.strip() or "integrity_check_failed")
    except Exception as e:
        log_exception(logger, "[DB Integrity] Integrity check failed", error=str(e))
        return ("error", f"exception: {e}")


def _loop() -> None:
    # Give the app time to start before first run
    time.sleep(30)
    while True:
        now = int(time.time())
        state._thread_health["db_integrity"] = {"last_heartbeat": now, "status": "ok", "error": None}

        backup_path = _BACKUP_DIR / f"smartify.db.backup.{now}"
        backup_err = _backup_db(backup_path)
        if backup_err:
            state._thread_health["db_integrity"] = {"last_heartbeat": now, "status": "error", "error": backup_err}

        status, result = _integrity_check()
        payload = {
            "status": status,
            "message": "ok" if status == "ok" else "integrity_check_failed",
            "result": result,
            "db_path": DB_PATH,
            "last_run_ts": now,
            "backup_error": backup_err,
        }
        _write_status(payload)
        _prune_backups()
        time.sleep(_INTERVAL_SECONDS)


def start_db_integrity_thread() -> None:
    t = threading.Thread(target=_loop, daemon=True, name="DbIntegrityThread")
    t.start()
    print("[DB Integrity] Background thread started")
