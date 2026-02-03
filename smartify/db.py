"""
Database layer for Smartify.
All SQLite interactions and DB helper functions are centralized here.
"""
import sqlite3
import time
import uuid
import json
from typing import Optional, Dict, Any, List, Tuple

from smartify.logging_setup import logger
from smartify.config import DB_PATH


# =========================
# DB Helper Functions
# =========================

def _safe_dict_from_row(row: Any, context: str = "unknown") -> Optional[dict]:
    """
    Safely convert sqlite3.Row to dict with forensic logging.
    Returns None if conversion fails instead of crashing.
    
    This should NEVER fail with a real sqlite3.Row, but if the database
    is corrupted or code passes wrong type, we log and continue safely.
    """
    if row is None:
        return None
    
    try:
        return dict(row)
    except ValueError as e:
        # dict() expects iterable of 2-tuples, this error means row is wrong type
        print(f"[DB] CRITICAL: dict(row) failed at {context}: {e}")
        print(f"[DB] CRITICAL:   type={type(row).__name__}")
        print(f"[DB] CRITICAL:   repr={repr(row)[:200]}")
        if isinstance(row, (list, tuple)) and row:
            print(f"[DB] CRITICAL:   first 5 items: {[repr(x)[:50] for x in row[:5]]}")
        return None


def _run_schema_migrations(conn: sqlite3.Connection, cur: sqlite3.Cursor) -> None:
    """
    Run automatic schema migrations.
    Checks for missing columns and applies ALTER TABLE as needed.
    This function is idempotent and safe to run on every startup.
    Future migrations can be added here following the same pattern.
    """
    # Migration: active_low column in relay_devices
    try:
        cur.execute("PRAGMA table_info(relay_devices)")
        columns = [row[1] for row in cur.fetchall()]  # Column name is at index 1
        if "active_low" not in columns:
            print("[DB] migrated: added active_low to relay_devices")
            cur.execute("ALTER TABLE relay_devices ADD COLUMN active_low BOOLEAN NOT NULL DEFAULT 0")
            conn.commit()
    except sqlite3.OperationalError as e:
        # Table might not exist yet (will be created by CREATE TABLE IF NOT EXISTS)
        # This is safe to ignore - migration will run on next startup after table is created
        pass
    except Exception as e:
        print(f"[DB Migration] Unexpected error checking/adding active_low column: {e}")
        # Don't raise - allow startup to continue, migration will retry on next startup
    
    try:
        cur.execute("PRAGMA table_info(relay_devices)")
        columns = [row[1] for row in cur.fetchall()]
        if "min_on_seconds" not in columns:
            print("[DB] migrated: added min_on_seconds to relay_devices")
            cur.execute("ALTER TABLE relay_devices ADD COLUMN min_on_seconds INTEGER NOT NULL DEFAULT 0")
            conn.commit()
        if "min_off_seconds" not in columns:
            print("[DB] migrated: added min_off_seconds to relay_devices")
            cur.execute("ALTER TABLE relay_devices ADD COLUMN min_off_seconds INTEGER NOT NULL DEFAULT 0")
            conn.commit()
    except Exception as e:
        print(f"[DB Migration] Unexpected error adding min_on_seconds/min_off_seconds: {e}")


# =========================
# DB Init & Connection
# =========================

def db_init() -> None:
    """Initialize database schema and run migrations."""
    print(f"[DB] Initializing database at: {DB_PATH}")
    conn = sqlite3.connect(DB_PATH)
    # Enable WAL mode for better concurrency and prevent database locked errors
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS temperature_readings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts INTEGER NOT NULL,
            sensor_index INTEGER NOT NULL,
            temperature_c REAL,
            humidity REAL
        );
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS gps_fixes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts INTEGER NOT NULL,
            lat REAL,
            lon REAL,
            speed_kmh REAL,
            course REAL,
            altitude_m REAL
        );
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS relay_states (
            name TEXT PRIMARY KEY,
            pin INTEGER NOT NULL,
            state TEXT NOT NULL,
            updated_at INTEGER NOT NULL
        );
        """
    )
    # New relay automation tables
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS relay_devices (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            pin INTEGER NOT NULL,
            command_on TEXT NOT NULL,
            command_off TEXT NOT NULL,
            active_low BOOLEAN NOT NULL DEFAULT 0,
            is_enabled BOOLEAN NOT NULL DEFAULT 1
        );
        """
    )
    
    # Run schema migrations
    _run_schema_migrations(conn, cur)
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS relay_state_new (
            relay_id TEXT PRIMARY KEY,
            state TEXT NOT NULL,
            mode TEXT NOT NULL,
            manual_until INTEGER,
            updated_at INTEGER NOT NULL,
            FOREIGN KEY (relay_id) REFERENCES relay_devices(id)
        );
        """
    )
    
    # Migration: Add new columns if they don't exist
    try:
        cur.execute("ALTER TABLE relay_state_new ADD COLUMN desired_state TEXT")
    except sqlite3.OperationalError:
        pass  # Column already exists
    
    try:
        cur.execute("ALTER TABLE relay_state_new ADD COLUMN actual_state TEXT")
    except sqlite3.OperationalError:
        pass  # Column already exists
    
    try:
        cur.execute("ALTER TABLE relay_state_new ADD COLUMN manual_state TEXT")
    except sqlite3.OperationalError:
        pass  # Column already exists
    
    try:
        cur.execute("ALTER TABLE relay_state_new ADD COLUMN last_applied_at INTEGER")
    except sqlite3.OperationalError:
        pass  # Column already exists
    
    # Migrate existing data: copy state to actual_state and desired_state if they're NULL
    cur.execute("""
        UPDATE relay_state_new 
        SET actual_state = state, 
            desired_state = state
        WHERE actual_state IS NULL OR desired_state IS NULL
    """)
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS relay_rules (
            id TEXT PRIMARY KEY,
            relay_id TEXT NOT NULL,
            name TEXT NOT NULL,
            is_enabled BOOLEAN NOT NULL DEFAULT 1,
            priority INTEGER NOT NULL DEFAULT 100,
            condition_json TEXT NOT NULL,
            action TEXT NOT NULL,
            cooldown_seconds INTEGER NOT NULL DEFAULT 60,
            last_triggered_at INTEGER,
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL,
            FOREIGN KEY (relay_id) REFERENCES relay_devices(id)
        );
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS relay_events (
            id TEXT PRIMARY KEY,
            relay_id TEXT NOT NULL,
            source TEXT NOT NULL,
            rule_id TEXT,
            old_state TEXT NOT NULL,
            new_state TEXT NOT NULL,
            reason TEXT,
            created_at INTEGER NOT NULL,
            FOREIGN KEY (relay_id) REFERENCES relay_devices(id),
            FOREIGN KEY (rule_id) REFERENCES relay_rules(id)
        );
        """
    )
    # Temperature snapshot tables for stable readings
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS sensor_snapshot (
            sensor_name TEXT PRIMARY KEY,
            avg_temp REAL,
            avg_humidity REAL,
            sample_count INTEGER NOT NULL DEFAULT 0,
            window_start INTEGER,
            window_end INTEGER,
            last_good_at INTEGER,
            updated_at INTEGER NOT NULL
        );
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS sensor_samples (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sensor_name TEXT NOT NULL,
            temp REAL,
            humidity REAL,
            ok INTEGER NOT NULL,
            created_at INTEGER NOT NULL
        );
        """
    )
    cur.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_sensor_samples_name_time 
        ON sensor_samples(sensor_name, created_at);
        """
    )
    # Initialize water level tables (delegated to water_level.db module)
    from smartify.water_level import db as water_level_db
    water_level_db.db_init_water_level(conn)
    
    # Initialize default heater relay device if it doesn't exist
    cur.execute("SELECT COUNT(*) FROM relay_devices WHERE name = 'heater'")
    if cur.fetchone()[0] == 0:
        heater_id = str(uuid.uuid4())
        # Default to pin 25 (user updated from 27), active_high (active_low=0)
        cur.execute(
            """INSERT INTO relay_devices (id, name, pin, command_on, command_off, active_low, is_enabled)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (heater_id, "heater", 25, "", "", 0, 1)  # Empty command strings, will use pinctrl
        )
        # Initialize relay state
        now = int(time.time())
        cur.execute(
            """INSERT INTO relay_state_new (relay_id, state, mode, manual_until, updated_at, actual_state, desired_state, manual_state, last_applied_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (heater_id, "off", "auto", None, now, "off", "off", None, now)
        )
    
    # Initialize default ventilator relay device if it doesn't exist
    cur.execute("SELECT COUNT(*) FROM relay_devices WHERE name = 'ventilator'")
    if cur.fetchone()[0] == 0:
        ventilator_id = str(uuid.uuid4())
        cur.execute(
            """INSERT INTO relay_devices (id, name, pin, command_on, command_off, active_low, is_enabled)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (ventilator_id, "ventilator", 26, "", "", 0, 1)
        )
        now = int(time.time())
        cur.execute(
            """INSERT INTO relay_state_new (relay_id, state, mode, manual_until, updated_at, actual_state, desired_state, manual_state, last_applied_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (ventilator_id, "off", "auto", None, now, "off", "off", None, now)
        )
    
    conn.commit()
    conn.close()
    print(f"[DB] Database initialization complete at: {DB_PATH}")


def db_connect() -> sqlite3.Connection:
    """
    Create a fresh SQLite connection with proper settings.
    Each call returns a NEW connection - never cache/reuse this.
    Caller must close the connection when done (or use with statement).
    """
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
    except Exception:
        pass  # WAL may fail on some systems; continue anyway
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


# =========================
# Temperature & Sensor Functions
# =========================

def db_insert_temp(ts: int, sensor_index: int, t: Optional[float], h: Optional[float]) -> None:
    with db_connect() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO temperature_readings (ts, sensor_index, temperature_c, humidity) VALUES (?, ?, ?, ?)",
            (ts, sensor_index, t, h),
        )
        conn.commit()


def db_insert_sensor_sample(sensor_name: str, temp: Optional[float], humidity: Optional[float], ok: bool, created_at: int) -> None:
    """Insert a raw sensor sample. Each call opens its own connection."""
    with db_connect() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO sensor_samples (sensor_name, temp, humidity, ok, created_at) VALUES (?, ?, ?, ?, ?)",
            (sensor_name, temp, humidity, 1 if ok else 0, created_at),
        )

        # Keep only last 15 minutes of samples to prevent DB growth
        cutoff = created_at - (15 * 60)
        cur.execute("DELETE FROM sensor_samples WHERE created_at < ?", (cutoff,))

        conn.commit()


def db_update_sensor_snapshot(
    sensor_name: str,
    avg_temp: Optional[float],
    avg_humidity: Optional[float],
    sample_count: int,
    window_start: int,
    window_end: int,
    last_good_at: int,
    updated_at: int
) -> None:
    """Update or insert sensor snapshot. Uses fresh connection per call."""
    with db_connect() as conn:
        cur = conn.cursor()

        # Forensics: verify row type if existing snapshot fetch returns unexpected type
        try:
            cur.execute("SELECT * FROM sensor_snapshot WHERE sensor_name = ?", (sensor_name,))
            row = cur.fetchone()
            if row is not None and not isinstance(row, sqlite3.Row) and not hasattr(row, "keys"):
                columns = [d[0] for d in cur.description] if cur.description else []
                sample = row[:10] if isinstance(row, (list, tuple)) else None
                logger.error(
                    "[db_update_sensor_snapshot] Unexpected row type: type=%s repr=%s columns=%s sample=%s",
                    type(row).__name__,
                    repr(row)[:200],
                    columns,
                    sample,
                )
        except Exception as e:
            logger.error("[db_update_sensor_snapshot] Forensics fetch failed: %s", e, exc_info=True)

        try:
            cur.execute(
                """
                INSERT INTO sensor_snapshot (
                    sensor_name, avg_temp, avg_humidity, sample_count,
                    window_start, window_end, last_good_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(sensor_name) DO UPDATE SET
                    avg_temp=excluded.avg_temp,
                    avg_humidity=excluded.avg_humidity,
                    sample_count=excluded.sample_count,
                    window_start=excluded.window_start,
                    window_end=excluded.window_end,
                    last_good_at=excluded.last_good_at,
                    updated_at=excluded.updated_at
                """,
                (
                    sensor_name,
                    avg_temp,
                    avg_humidity,
                    sample_count,
                    window_start,
                    window_end,
                    last_good_at,
                    updated_at,
                ),
            )
        except Exception as e:
            logger.error("[db_update_sensor_snapshot] Failed to upsert snapshot: %s", e, exc_info=True)
            return

        conn.commit()
        logger.debug("[db_update_sensor_snapshot] Saved snapshot for %s", sensor_name)


def db_upsert_sensor_snapshot(
    sensor_name: str,
    avg_temp: Optional[float],
    avg_humidity: Optional[float],
    sample_count: int,
    window_start: int,
    window_end: int,
    last_good_at: int,
    updated_at: int,
) -> None:
    """Alias for db_update_sensor_snapshot (kept for backward compatibility)."""
    db_update_sensor_snapshot(
        sensor_name,
        avg_temp,
        avg_humidity,
        sample_count,
        window_start,
        window_end,
        last_good_at,
        updated_at,
    )


def db_get_sensor_snapshot(sensor_name: str) -> Optional[Dict[str, Any]]:
    """Get sensor snapshot. Uses fresh connection per call."""
    with db_connect() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM sensor_snapshot WHERE sensor_name = ?", (sensor_name,))
        row = cur.fetchone()
        return dict(row) if row else None


def db_query_temp_since(since_ts: int, sensor_index: Optional[int] = None) -> List[Dict[str, Any]]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    if sensor_index is None:
        cur.execute(
            "SELECT ts, sensor_index, temperature_c, humidity FROM temperature_readings WHERE ts >= ? ORDER BY ts ASC",
            (since_ts,),
        )
    else:
        cur.execute(
            "SELECT ts, sensor_index, temperature_c, humidity FROM temperature_readings WHERE ts >= ? AND sensor_index = ? ORDER BY ts ASC",
            (since_ts, sensor_index),
        )
    rows = [_safe_dict_from_row(r, context="db_query_temperature") for r in cur.fetchall()]
    rows = [r for r in rows if r is not None]  # Filter out None values from failed conversions
    conn.close()
    return rows


# =========================
# GPS Functions
# =========================

def db_insert_gps(ts: int, lat: Optional[float], lon: Optional[float], speed_kmh: Optional[float],
                  course: Optional[float], altitude_m: Optional[float]) -> None:
    conn = sqlite3.connect(DB_PATH, timeout=5.0)
    cur = conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA busy_timeout=5000")
    cur.execute("PRAGMA synchronous=NORMAL")
    cur.execute(
        "INSERT INTO gps_fixes (ts, lat, lon, speed_kmh, course, altitude_m) VALUES (?, ?, ?, ?, ?, ?)",
        (ts, lat, lon, speed_kmh, course, altitude_m),
    )
    conn.commit()
    conn.close()


def db_query_gps_since(since_ts: int, limit: int = 1000) -> List[Dict[str, Any]]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(
        "SELECT ts, lat, lon, speed_kmh, course, altitude_m FROM gps_fixes WHERE ts >= ? ORDER BY ts ASC LIMIT ?",
        (since_ts, limit),
    )
    rows = [_safe_dict_from_row(r, context="db_query_gps_since") for r in cur.fetchall()]
    rows = [r for r in rows if r is not None]  # Filter out None values
    conn.close()
    return rows


# =========================
# Legacy Relay State Functions
# =========================

def db_get_relay_state(name: str) -> Optional[Dict[str, Any]]:
    """Get relay state from database. Returns None if not found."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT name, pin, state, updated_at FROM relay_states WHERE name = ?", (name,))
    row = cur.fetchone()
    conn.close()
    if row:
        return _safe_dict_from_row(row, context="db_get_relay_state")
    return None


def db_set_relay_state(name: str, pin: int, state: str) -> None:
    """Set relay state in database. state must be 'on' or 'off'."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    now = int(time.time())
    cur.execute(
        "INSERT OR REPLACE INTO relay_states (name, pin, state, updated_at) VALUES (?, ?, ?, ?)",
        (name, pin, state, now),
    )
    conn.commit()
    conn.close()


# =========================
# Relay Automation DB Functions
# =========================

def db_get_relay_device_by_name(name: str) -> Optional[Dict[str, Any]]:
    """Get relay device by name."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT * FROM relay_devices WHERE name = ?", (name,))
    row = cur.fetchone()
    conn.close()
    return _safe_dict_from_row(row, context="db_get_relay_device_by_name")


def db_get_relay_device(relay_id: str) -> Optional[Dict[str, Any]]:
    """Get relay device by ID."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT * FROM relay_devices WHERE id = ?", (relay_id,))
    row = cur.fetchone()
    conn.close()
    return _safe_dict_from_row(row, context="db_get_relay_device")


def db_list_relay_devices() -> List[Dict[str, Any]]:
    """List all relay devices."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT * FROM relay_devices ORDER BY name")
    rows = cur.fetchall()
    conn.close()
    return [_safe_dict_from_row(row, context="db_list_relay_devices") for row in rows if _safe_dict_from_row(row, context="db_list_relay_devices") is not None]


def db_create_relay_device(
    name: str,
    pin: int,
    active_low: bool = False,
    is_enabled: bool = True,
    min_on_seconds: int = 0,
    min_off_seconds: int = 0,
) -> str:
    """Create a new relay device. Returns device ID."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    relay_id = str(uuid.uuid4())
    cur.execute(
        """INSERT INTO relay_devices (id, name, pin, command_on, command_off, active_low, is_enabled, min_on_seconds, min_off_seconds)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (relay_id, name, pin, "", "", 1 if active_low else 0, 1 if is_enabled else 0, min_on_seconds, min_off_seconds),
    )
    conn.commit()
    conn.close()
    return relay_id


def db_update_relay_device(
    relay_id: str,
    name: Optional[str] = None,
    pin: Optional[int] = None,
    active_low: Optional[bool] = None,
    is_enabled: Optional[bool] = None,
    min_on_seconds: Optional[int] = None,
    min_off_seconds: Optional[int] = None,
) -> bool:
    """Update relay device fields. Returns True if updated."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    updates = []
    params: List[Any] = []
    if name is not None:
        updates.append("name = ?")
        params.append(name)
    if pin is not None:
        updates.append("pin = ?")
        params.append(pin)
    if active_low is not None:
        updates.append("active_low = ?")
        params.append(1 if active_low else 0)
    if is_enabled is not None:
        updates.append("is_enabled = ?")
        params.append(1 if is_enabled else 0)
    if min_on_seconds is not None:
        updates.append("min_on_seconds = ?")
        params.append(min_on_seconds)
    if min_off_seconds is not None:
        updates.append("min_off_seconds = ?")
        params.append(min_off_seconds)
    
    if not updates:
        conn.close()
        return False
    
    params.append(relay_id)
    cur.execute(f"UPDATE relay_devices SET {', '.join(updates)} WHERE id = ?", params)
    conn.commit()
    updated = cur.rowcount > 0
    conn.close()
    return updated


def db_get_relay_state_new(relay_id: str) -> Optional[Dict[str, Any]]:
    """Get relay state (new table)."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # CRITICAL: Set IMMEDIATELY after connect
    conn.execute("PRAGMA busy_timeout=5000")
    cur = conn.cursor()
    cur.execute("SELECT * FROM relay_state_new WHERE relay_id = ?", (relay_id,))
    row = cur.fetchone()
    conn.close()
    if row:
        state_dict = dict(row)  # Now safe - row is sqlite3.Row
        
        # Ensure backward compatibility: if new columns are NULL, use old 'state' field
        if state_dict.get("actual_state") is None:
            state_dict["actual_state"] = state_dict.get("state", "off")
        if state_dict.get("desired_state") is None:
            state_dict["desired_state"] = state_dict.get("state", "off")
        return state_dict
    return None


def db_create_relay_state_new(
    relay_id: str,
    state: str = "off",
    mode: str = "auto",
    manual_until: Optional[int] = None,
    manual_state: Optional[str] = None,
) -> None:
    """Create relay_state_new row for a relay."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    now = int(time.time())
    cur.execute(
        """INSERT INTO relay_state_new (relay_id, state, mode, manual_until, updated_at, actual_state, desired_state, manual_state, last_applied_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (relay_id, state, mode, manual_until, now, state, state, manual_state, now),
    )
    conn.commit()
    conn.close()


def db_set_relay_state_new(relay_id: str, state: str, mode: str, manual_until: Optional[int] = None) -> None:
    """Set relay state (new table). DEPRECATED: Use db_update_relay_state_new instead."""
    db_update_relay_state_new(
        relay_id=relay_id,
        actual_state=state,
        desired_state=state,
        mode=mode,
        manual_until=manual_until
    )


def db_update_relay_state_new(
    relay_id: str,
    actual_state: Optional[str] = None,
    desired_state: Optional[str] = None,
    mode: Optional[str] = None,
    manual_state: Optional[str] = None,
    manual_until: Optional[int] = None,
    last_applied_at: Optional[int] = None
) -> None:
    """Update relay state fields. Only updates provided fields."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA busy_timeout=5000")
    cur = conn.cursor()
    now = int(time.time())
    
    # Build dynamic UPDATE query
    updates = []
    params = []
    
    if actual_state is not None:
        updates.append("actual_state = ?")
        updates.append("state = ?")  # Keep old 'state' field in sync for backward compat
        params.append(actual_state)
        params.append(actual_state)
    
    if desired_state is not None:
        updates.append("desired_state = ?")
        params.append(desired_state)
    
    # Handle mode: when switching to auto, always clear manual fields
    if mode is not None:
        updates.append("mode = ?")
        params.append(mode)
        if mode == "auto":
            # Always clear manual fields when switching to auto (unless explicitly set below)
            updates.append("manual_state = NULL")
            updates.append("manual_until = NULL")
    
    # Only set manual_state/manual_until if mode is not being set to auto
    # (if mode is auto, they were already cleared above)
    if manual_state is not None and mode != "auto":
        updates.append("manual_state = ?")
        params.append(manual_state)
    
    if manual_until is not None and mode != "auto":
        updates.append("manual_until = ?")
        params.append(manual_until)
    
    if last_applied_at is not None:
        updates.append("last_applied_at = ?")
        params.append(last_applied_at)
    
    updates.append("updated_at = ?")
    params.append(now)
    params.append(relay_id)
    
    if updates:
        query = f"UPDATE relay_state_new SET {', '.join(updates)} WHERE relay_id = ?"
        cur.execute(query, params)
    
    conn.commit()
    conn.close()


# =========================
# Relay Rules Functions
# =========================

# Note: These functions depend on validate_rule_action which is in app.py
# We'll need to handle this import carefully

def db_list_relay_rules(relay_id: str) -> List[Dict[str, Any]]:
    """List rules for a relay. Handles JSON parsing errors gracefully."""
    # Import validate_rule_action from validators module
    from smartify.validators import validate_rule_action
    
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT * FROM relay_rules WHERE relay_id = ? ORDER BY priority ASC, created_at ASC", (relay_id,))
    rows = cur.fetchall()
    conn.close()
    result = []
    for row in rows:
        r = _safe_dict_from_row(row, context="db_list_relay_rules")
        if not r:
            continue  # Skip if conversion failed
        
        # Parse condition_json - handle errors gracefully
        condition_json_str = r.get("condition_json", "")
        if condition_json_str:
            try:
                r["condition"] = json.loads(condition_json_str)
            except (json.JSONDecodeError, TypeError, ValueError) as e:
                # If JSON parsing fails, set condition to empty dict (will be caught by evaluate_single_rule)
                print(f"[DB] Error parsing condition_json for rule {r.get('id', 'unknown')}: {e}")
                r["condition"] = {}
        else:
            r["condition"] = {}
        
        # Parse action (JSON or legacy string)
        action_raw = r.get("action", "")
        parsed_action = None
        if isinstance(action_raw, str):
            action_str = action_raw.strip()
            if action_str.startswith("{"):
                try:
                    parsed_action = json.loads(action_str)
                except (json.JSONDecodeError, TypeError, ValueError):
                    parsed_action = action_str
            else:
                parsed_action = action_str
        else:
            parsed_action = action_raw
        
        ok, _err, normalized_action = validate_rule_action(parsed_action)
        r["action"] = normalized_action if ok else parsed_action
        # Convert SQLite integer boolean to Python boolean
        r["is_enabled"] = bool(r.get("is_enabled", 1))
        result.append(r)
    return result


def db_get_relay_rule(rule_id: str) -> Optional[Dict[str, Any]]:
    """Get a rule by ID."""
    # Import validate_rule_action from validators module
    from smartify.validators import validate_rule_action
    
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT * FROM relay_rules WHERE id = ?", (rule_id,))
    row = cur.fetchone()
    conn.close()
    if row:
        r = _safe_dict_from_row(row, context="db_get_relay_rule")
        if not r:
            return None
        r["condition"] = json.loads(r["condition_json"])
        action_raw = r.get("action", "")
        parsed_action = None
        if isinstance(action_raw, str):
            action_str = action_raw.strip()
            if action_str.startswith("{"):
                try:
                    parsed_action = json.loads(action_str)
                except (json.JSONDecodeError, TypeError, ValueError):
                    parsed_action = action_str
            else:
                parsed_action = action_str
        else:
            parsed_action = action_raw
        ok, _err, normalized_action = validate_rule_action(parsed_action)
        r["action"] = normalized_action if ok else parsed_action
        # Convert SQLite integer boolean to Python boolean
        r["is_enabled"] = bool(r.get("is_enabled", 1))
        return r
    return None


def db_create_relay_rule(relay_id: str, name: str, condition: Dict[str, Any], action: Dict[str, Any],
                         priority: int = 100, cooldown_seconds: int = 60, is_enabled: bool = True) -> str:
    """Create a new rule. Returns rule ID."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    rule_id = str(uuid.uuid4())
    now = int(time.time())
    cur.execute(
        """INSERT INTO relay_rules (id, relay_id, name, is_enabled, priority, condition_json, action,
           cooldown_seconds, last_triggered_at, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (rule_id, relay_id, name, 1 if is_enabled else 0, priority, json.dumps(condition),
         json.dumps(action), cooldown_seconds, None, now, now),
    )
    conn.commit()
    conn.close()
    return rule_id


def db_update_relay_rule(rule_id: str, name: Optional[str] = None, condition: Optional[Dict[str, Any]] = None,
                         action: Optional[Dict[str, Any]] = None, priority: Optional[int] = None,
                         cooldown_seconds: Optional[int] = None, is_enabled: Optional[bool] = None) -> bool:
    """Update a rule. Returns True if updated."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    
    updates = []
    params = []
    if name is not None:
        updates.append("name = ?")
        params.append(name)
    if condition is not None:
        updates.append("condition_json = ?")
        params.append(json.dumps(condition))
    if action is not None:
        updates.append("action = ?")
        params.append(json.dumps(action))
    if priority is not None:
        updates.append("priority = ?")
        params.append(priority)
    if cooldown_seconds is not None:
        updates.append("cooldown_seconds = ?")
        params.append(cooldown_seconds)
    if is_enabled is not None:
        updates.append("is_enabled = ?")
        params.append(1 if is_enabled else 0)
    
    if not updates:
        conn.close()
        return False
    
    updates.append("updated_at = ?")
    params.append(int(time.time()))
    params.append(rule_id)
    
    cur.execute(f"UPDATE relay_rules SET {', '.join(updates)} WHERE id = ?", params)
    conn.commit()
    updated = cur.rowcount > 0
    conn.close()
    return updated


def db_delete_relay_rule(rule_id: str) -> bool:
    """Delete a rule. Returns True if deleted."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("DELETE FROM relay_rules WHERE id = ?", (rule_id,))
    conn.commit()
    deleted = cur.rowcount > 0
    conn.close()
    return deleted


def db_log_relay_event(relay_id: str, source: str, old_state: str, new_state: str,
                       reason: Optional[str] = None, rule_id: Optional[str] = None) -> None:
    """Log a relay state change event."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    event_id = str(uuid.uuid4())
    now = int(time.time())
    cur.execute(
        """INSERT INTO relay_events (id, relay_id, source, rule_id, old_state, new_state, reason, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (event_id, relay_id, source, rule_id, old_state, new_state, reason, now),
    )
    conn.commit()
    conn.close()


def db_get_relay_events(relay_id: str, limit: int = 50) -> List[Dict[str, Any]]:
    """Get recent events for a relay."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM relay_events WHERE relay_id = ? ORDER BY created_at DESC LIMIT ?",
        (relay_id, limit),
    )
    rows = cur.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def db_update_rule_last_triggered(rule_id: str) -> None:
    """Update rule's last_triggered_at timestamp."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    now = int(time.time())
    cur.execute("UPDATE relay_rules SET last_triggered_at = ? WHERE id = ?", (now, rule_id))
    conn.commit()
    conn.close()

