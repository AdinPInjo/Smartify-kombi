import os
import time
import sqlite3
import threading
import subprocess
import uuid
import json
from collections import deque
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple

from fastapi import FastAPI, Request, Form, Header, Body
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware

# =========================
# Config (no hardcoded IPs)
# =========================

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = Path(os.environ.get("SMARTIFY_STATIC_DIR", str(BASE_DIR / "static")))
# normalize & resolve path (works with absolute or relative)
STATIC_DIR = STATIC_DIR.expanduser().resolve()
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "smartify.db"

SMARTIFY_REQUIRE_AUTH = os.environ.get("SMARTIFY_REQUIRE_AUTH", "1").lower() not in ("0", "false", "no")
SMARTIFY_API_KEY = os.environ.get("SMARTIFY_API_KEY", "").strip()

SMARTIFY_USERNAME = os.environ.get("SMARTIFY_USERNAME", "adinpinjo")
SMARTIFY_PASSWORD = os.environ.get("SMARTIFY_PASSWORD", "changeme")

SMARTIFY_SESSION_SECRET = os.environ.get("SMARTIFY_SESSION_SECRET", "").strip() or "change-me-in-env"

GPS_DEVICE = os.environ.get("SMARTIFY_GPS_DEVICE", "/dev/ttyACM0").strip()
GPS_BAUD = int(os.environ.get("SMARTIFY_GPS_BAUD", "9600"))

DHT22_PINS_RAW = os.environ.get("SMARTIFY_DHT22_PINS", "4").strip()
DHT22_PINS: List[int] = []
for part in [p.strip() for p in DHT22_PINS_RAW.split(",") if p.strip()]:
    try:
        DHT22_PINS.append(int(part))
    except ValueError:
        pass
if not DHT22_PINS:
    DHT22_PINS = [4]

SENSOR_LOG_INTERVAL = int(os.environ.get("SMARTIFY_SENSOR_LOG_INTERVAL", "30"))
SMARTIFY_TRUST_LOCALHOST = os.environ.get("SMARTIFY_TRUST_LOCALHOST", "0").lower() in ("1", "true", "yes")


# =========================
# App + Middleware
# =========================

app = FastAPI(title="Smartify Dashboard API")

# CORS middleware - allow all origins for local network access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins for local network
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(
    SessionMiddleware,
    secret_key=SMARTIFY_SESSION_SECRET,
    same_site="lax",
    https_only=False,
)

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# =========================
# DB helpers
# =========================

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
    
    # Future migrations can be added here:
    # try:
    #     cur.execute("PRAGMA table_info(relay_devices)")
    #     columns = [row[1] for row in cur.fetchall()]
    #     if "new_column" not in columns:
    #         print("[DB] migrated: added new_column to relay_devices")
    #         cur.execute("ALTER TABLE relay_devices ADD COLUMN new_column TEXT DEFAULT ''")
    #         conn.commit()
    # except Exception as e:
    #     print(f"[DB Migration] Error adding new_column: {e}")


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
    
    conn.commit()
    conn.close()
    print(f"[DB] Database initialization complete at: {DB_PATH}")


def db_insert_temp(ts: int, sensor_index: int, t: Optional[float], h: Optional[float]) -> None:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO temperature_readings (ts, sensor_index, temperature_c, humidity) VALUES (?, ?, ?, ?)",
        (ts, sensor_index, t, h),
    )
    conn.commit()
    conn.close()


def db_insert_sensor_sample(sensor_name: str, temp: Optional[float], humidity: Optional[float], ok: bool, created_at: int) -> None:
    """Insert a raw sensor sample (optional, for debugging)."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO sensor_samples (sensor_name, temp, humidity, ok, created_at) VALUES (?, ?, ?, ?, ?)",
        (sensor_name, temp, humidity, 1 if ok else 0, created_at),
    )
    conn.commit()
    conn.close()
    
    # Keep only last 15 minutes of samples to prevent DB growth
    cutoff = created_at - (15 * 60)
    cur.execute("DELETE FROM sensor_samples WHERE created_at < ?", (cutoff,))
    conn.commit()
    conn.close()


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
    """Update or insert sensor snapshot."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO sensor_snapshot 
           (sensor_name, avg_temp, avg_humidity, sample_count, window_start, window_end, last_good_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(sensor_name) DO UPDATE SET
           avg_temp = excluded.avg_temp,
           avg_humidity = excluded.avg_humidity,
           sample_count = excluded.sample_count,
           window_start = excluded.window_start,
           window_end = excluded.window_end,
           last_good_at = excluded.last_good_at,
           updated_at = excluded.updated_at""",
        (sensor_name, avg_temp, avg_humidity, sample_count, window_start, window_end, last_good_at, updated_at),
    )
    conn.commit()
    conn.close()


def db_get_sensor_snapshot(sensor_name: str) -> Optional[Dict[str, Any]]:
    """Get sensor snapshot."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT * FROM sensor_snapshot WHERE sensor_name = ?", (sensor_name,))
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def db_insert_gps(ts: int, lat: Optional[float], lon: Optional[float], speed_kmh: Optional[float],
                  course: Optional[float], altitude_m: Optional[float]) -> None:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO gps_fixes (ts, lat, lon, speed_kmh, course, altitude_m) VALUES (?, ?, ?, ?, ?, ?)",
        (ts, lat, lon, speed_kmh, course, altitude_m),
    )
    conn.commit()
    conn.close()


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
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def db_query_gps_since(since_ts: int, limit: int = 1000) -> List[Dict[str, Any]]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(
        "SELECT ts, lat, lon, speed_kmh, course, altitude_m FROM gps_fixes WHERE ts >= ? ORDER BY ts ASC LIMIT ?",
        (since_ts, limit),
    )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def db_get_relay_state(name: str) -> Optional[Dict[str, Any]]:
    """Get relay state from database. Returns None if not found."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT name, pin, state, updated_at FROM relay_states WHERE name = ?", (name,))
    row = cur.fetchone()
    conn.close()
    if row:
        return dict(row)
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
# Relay automation DB helpers
# =========================

def db_get_relay_device_by_name(name: str) -> Optional[Dict[str, Any]]:
    """Get relay device by name."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT * FROM relay_devices WHERE name = ?", (name,))
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def db_get_relay_device(relay_id: str) -> Optional[Dict[str, Any]]:
    """Get relay device by ID."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT * FROM relay_devices WHERE id = ?", (relay_id,))
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def db_list_relay_devices() -> List[Dict[str, Any]]:
    """List all relay devices."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT * FROM relay_devices ORDER BY name")
    rows = cur.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def db_get_relay_state_new(relay_id: str) -> Optional[Dict[str, Any]]:
    """Get relay state (new table)."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA busy_timeout=5000")
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT * FROM relay_state_new WHERE relay_id = ?", (relay_id,))
    row = cur.fetchone()
    conn.close()
    if row:
        state_dict = dict(row)
        # Ensure backward compatibility: if new columns are NULL, use old 'state' field
        if state_dict.get("actual_state") is None:
            state_dict["actual_state"] = state_dict.get("state", "off")
        if state_dict.get("desired_state") is None:
            state_dict["desired_state"] = state_dict.get("state", "off")
        return state_dict
    return None


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


def db_list_relay_rules(relay_id: str) -> List[Dict[str, Any]]:
    """List rules for a relay."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT * FROM relay_rules WHERE relay_id = ? ORDER BY priority ASC, created_at ASC", (relay_id,))
    rows = cur.fetchall()
    conn.close()
    result = []
    for row in rows:
        r = dict(row)
        r["condition"] = json.loads(r["condition_json"])
        # Convert SQLite integer boolean to Python boolean
        r["is_enabled"] = bool(r.get("is_enabled", 1))
        result.append(r)
    return result


def db_get_relay_rule(rule_id: str) -> Optional[Dict[str, Any]]:
    """Get a rule by ID."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT * FROM relay_rules WHERE id = ?", (rule_id,))
    row = cur.fetchone()
    conn.close()
    if row:
        r = dict(row)
        r["condition"] = json.loads(r["condition_json"])
        # Convert SQLite integer boolean to Python boolean
        r["is_enabled"] = bool(r.get("is_enabled", 1))
        return r
    return None


def db_create_relay_rule(relay_id: str, name: str, condition: Dict[str, Any], action: str,
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
         action, cooldown_seconds, None, now, now),
    )
    conn.commit()
    conn.close()
    return rule_id


def db_update_relay_rule(rule_id: str, name: Optional[str] = None, condition: Optional[Dict[str, Any]] = None,
                         action: Optional[str] = None, priority: Optional[int] = None,
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
        params.append(action)
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


# =========================
# Auth helpers
# =========================

def is_localhost(request: Request) -> bool:
    host = request.client.host if request.client else ""
    return host in ("127.0.0.1", "::1", "localhost")


def is_authenticated(request: Request, x_api_key: Optional[str]) -> bool:
    if not SMARTIFY_REQUIRE_AUTH:
        return True

    if SMARTIFY_TRUST_LOCALHOST and is_localhost(request):
        return True

    if request.session.get("logged_in") is True:
        return True

    if SMARTIFY_API_KEY and x_api_key and x_api_key.strip() == SMARTIFY_API_KEY:
        return True

    return False


def require_auth(request: Request, x_api_key: Optional[str]) -> Optional[JSONResponse]:
    if is_authenticated(request, x_api_key):
        return None
    return JSONResponse({"error": "unauthorized"}, status_code=401)


# =========================
# Sensor: DHT22
# =========================

_dht_lock = threading.Lock()
_temp_latest: Dict[str, Any] = {
    "ts": None,
    "sensors": [],
}

# Temperature snapshot system for stable readings
_sensor_samples: Dict[str, deque] = {}  # sensor_name -> deque of (temp, humidity, timestamp, ok)
_sensor_samples_lock = threading.Lock()
SENSOR_SAMPLE_INTERVAL = 5  # Sample every 5 seconds
SENSOR_SNAPSHOT_INTERVAL = 60  # Update snapshot every 60 seconds
SENSOR_STALE_THRESHOLD = 600  # 10 minutes without valid samples = stale
SENSOR_WARMUP_SAMPLES = 6  # Need at least 6 samples (30s) before snapshot is "ready"

def read_dht22_all() -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    try:
        import adafruit_dht
        import board
    except Exception as e:
        for idx, pin in enumerate(DHT22_PINS):
            results.append({
                "sensor_index": idx,
                "pin": pin,
                "temperature_c": None,
                "humidity": None,
                "ok": False,
                "error": f"DHT libs not installed: {e}"
            })
        return results

    board_attr_map = {i: f"D{i}" for i in range(0, 28)}
    now = int(time.time())

    with _dht_lock:
        for idx, pin in enumerate(DHT22_PINS):
            t = None
            h = None
            ok = False
            err = None

            try:
                attr = board_attr_map.get(pin)
                if not attr or not hasattr(board, attr):
                    raise RuntimeError(f"Unsupported pin mapping for BCM {pin} (board.{attr} not found)")

                gpio_obj = getattr(board, attr)
                sensor = adafruit_dht.DHT22(gpio_obj, use_pulseio=False)

                try:
                    t = float(sensor.temperature) if sensor.temperature is not None else None
                    h = float(sensor.humidity) if sensor.humidity is not None else None
                    ok = (t is not None and h is not None)
                finally:
                    try:
                        sensor.exit()
                    except Exception:
                        pass

            except Exception as e:
                err = str(e)

            results.append({
                "sensor_index": idx,
                "pin": pin,
                "temperature_c": t,
                "humidity": h,
                "ok": ok,
                "error": err
            })

            db_insert_temp(now, idx, t, h)

    return results


def _dht22_poller_thread() -> None:
    """Background thread that polls DHT22 sensors at fixed intervals."""
    global _temp_latest
    
    while True:
        try:
            results = read_dht22_all()
            _temp_latest.update({
                "ts": int(time.time()),
                "sensors": results,
            })
        except Exception as e:
            _temp_latest.update({
                "ts": int(time.time()),
                "sensors": [],
                "error": str(e),
            })
        
        # Poll every SENSOR_LOG_INTERVAL seconds (default 30s)
        time.sleep(SENSOR_LOG_INTERVAL)


def _sensor_sampler_thread() -> None:
    """
    Background thread that samples DHT22 sensors every 5 seconds,
    accumulates samples in memory, and updates snapshot every 60 seconds.
    """
    global _sensor_samples
    
    # Map sensor_index to sensor_name (kombi=0, garaza=1)
    sensor_name_map = {0: "kombi", 1: "garaza"}
    
    # Initialize deques for each sensor
    with _sensor_samples_lock:
        for idx in range(len(DHT22_PINS)):
            sensor_name = sensor_name_map.get(idx, f"sensor_{idx}")
            if sensor_name not in _sensor_samples:
                _sensor_samples[sensor_name] = deque(maxlen=15)  # Keep last 15 samples (75s max)
    
    last_snapshot_time = int(time.time())
    last_snapshot_time = (last_snapshot_time // SENSOR_SNAPSHOT_INTERVAL) * SENSOR_SNAPSHOT_INTERVAL  # Align to minute boundary
    
    while True:
        try:
            now = int(time.time())
            
            # Read all sensors
            results = read_dht22_all()
            
            # Store samples in memory
            with _sensor_samples_lock:
                for result in results:
                    sensor_idx = result.get("sensor_index", -1)
                    sensor_name = sensor_name_map.get(sensor_idx)
                    if not sensor_name:
                        continue
                    
                    temp = result.get("temperature_c")
                    humidity = result.get("humidity")
                    ok = result.get("ok", False)
                    
                    # Store sample (temp, humidity, timestamp, ok)
                    if sensor_name not in _sensor_samples:
                        _sensor_samples[sensor_name] = deque(maxlen=15)
                    _sensor_samples[sensor_name].append((temp, humidity, now, ok))
                    
                    # Optionally store in DB for debugging (can be disabled for performance)
                    # db_insert_sensor_sample(sensor_name, temp, humidity, ok, now)
            
            # Check if it's time to update snapshot (every 60 seconds, aligned to minute boundary)
            current_window = (now // SENSOR_SNAPSHOT_INTERVAL) * SENSOR_SNAPSHOT_INTERVAL
            if current_window > last_snapshot_time:
                # Time to compute and store snapshot
                window_start = last_snapshot_time
                window_end = current_window
                
                with _sensor_samples_lock:
                    for sensor_name, samples in _sensor_samples.items():
                        # Get valid samples from the last 60-second window
                        valid_samples = [
                            (t, h) for t, h, ts, ok in samples
                            if ok and t is not None and h is not None and ts >= window_start and ts < window_end
                        ]
                        
                        if valid_samples:
                            # Compute average
                            avg_temp = sum(t for t, h in valid_samples) / len(valid_samples)
                            avg_humidity = sum(h for t, h in valid_samples) / len(valid_samples)
                            sample_count = len(valid_samples)
                            last_good_at = now
                            
                            # Update snapshot
                            db_update_sensor_snapshot(
                                sensor_name=sensor_name,
                                avg_temp=avg_temp,
                                avg_humidity=avg_humidity,
                                sample_count=sample_count,
                                window_start=window_start,
                                window_end=window_end,
                                last_good_at=last_good_at,
                                updated_at=now
                            )
                            print(f"[Sensor Snapshot] Updated {sensor_name}: {avg_temp:.1f}°C (from {sample_count} samples)")
                        else:
                            # No valid samples in this window - keep previous snapshot (do NOT overwrite)
                            existing = db_get_sensor_snapshot(sensor_name)
                            if existing:
                                print(f"[Sensor Snapshot] No valid samples for {sensor_name} in window, keeping previous snapshot")
                            # If no existing snapshot, we don't create one (will be marked as stale)
                
                last_snapshot_time = current_window
            
            # Sample every 5 seconds
            time.sleep(SENSOR_SAMPLE_INTERVAL)
            
        except Exception as e:
            print(f"[Sensor Sampler] Error: {e}")
            import traceback
            traceback.print_exc()
            time.sleep(SENSOR_SAMPLE_INTERVAL)


# =========================
# Sensor: GPS (USB NMEA)
# =========================

_gps_latest: Dict[str, Any] = {
    "ts": None,
    "lat": None,
    "lon": None,
    "speed_kmh": None,
    "course": None,
    "altitude_m": None,
    "satellites": None,
    "source": "nmea",
    "device": GPS_DEVICE,
    "ok": False,
    "error": None,
}


def _nmea_to_decimal(coord: str, hemi: str) -> Optional[float]:
    """
    Convert NMEA coordinate format (ddmm.mmmm or dddmm.mmmm) to decimal degrees.
    
    - Latitude (N/S): uses 2 digits for degrees (ddmm.mmmm)
    - Longitude (E/W): uses 3 digits for degrees (dddmm.mmmm)
    """
    if not coord or not hemi:
        return None
    try:
        if "." not in coord:
            return None
        
        # Determine degrees length based on hemisphere:
        # N/S (latitude) = 2 digits, E/W (longitude) = 3 digits
        hemi_upper = hemi.upper()
        if hemi_upper in ("N", "S"):
            deg_len = 2  # Latitude: ddmm.mmmm
        elif hemi_upper in ("E", "W"):
            deg_len = 3  # Longitude: dddmm.mmmm
        else:
            return None  # Invalid hemisphere
        
        deg = float(coord[:deg_len])
        minutes = float(coord[deg_len:])
        dec = deg + minutes / 60.0
        
        # Apply sign based on hemisphere
        if hemi_upper in ("S", "W"):
            dec *= -1.0
        
        return dec
    except Exception:
        return None


def _gps_reader_thread() -> None:
    global _gps_latest
    try:
        import serial
    except Exception as e:
        _gps_latest["ok"] = False
        _gps_latest["error"] = f"pyserial not available: {e}"
        return

    while True:
        try:
            if not Path(GPS_DEVICE).exists():
                _gps_latest["ok"] = False
                _gps_latest["error"] = f"GPS device not found: {GPS_DEVICE}"
                time.sleep(2)
                continue

            # Use timeout for serial reads to prevent blocking
            with serial.Serial(GPS_DEVICE, GPS_BAUD, timeout=2) as ser:
                _gps_latest["error"] = None
                while True:
                    try:
                        # readline with timeout will return empty string if timeout
                        line = ser.readline().decode(errors="ignore").strip()
                        if not line or not line.startswith("$"):
                            continue

                        parts = line.split(",")
                        if not parts:
                            continue
                        sentence = parts[0]
                        now = int(time.time())

                        if sentence.endswith("RMC") and len(parts) >= 12:
                            status = parts[2] if len(parts) > 2 else ""
                            if status != "A":
                                continue

                            lat = _nmea_to_decimal(parts[3], parts[4])
                            lon = _nmea_to_decimal(parts[5], parts[6])

                            speed_kn = None
                            course = None
                            try:
                                speed_kn = float(parts[7]) if parts[7] else None
                            except Exception:
                                speed_kn = None
                            try:
                                course = float(parts[8]) if parts[8] else None
                            except Exception:
                                course = None

                            speed_kmh = speed_kn * 1.852 if speed_kn is not None else None

                            _gps_latest.update({
                                "ts": now,
                                "lat": lat,
                                "lon": lon,
                                "speed_kmh": speed_kmh,
                                "course": course,
                                "ok": True,
                                "error": None,
                            })
                            db_insert_gps(now, lat, lon, speed_kmh, course, _gps_latest.get("altitude_m"))

                        if sentence.endswith("GGA") and len(parts) >= 10:
                            fix = parts[6] if len(parts) > 6 else "0"
                            if fix == "0":
                                continue

                            lat = _nmea_to_decimal(parts[2], parts[3])
                            lon = _nmea_to_decimal(parts[4], parts[5])

                            alt = None
                            try:
                                alt = float(parts[9]) if parts[9] else None
                            except Exception:
                                alt = None

                            # Extract satellite count (field 7 in GGA sentence)
                            satellites = None
                            try:
                                if len(parts) > 7 and parts[7]:
                                    satellites = int(parts[7])
                            except Exception:
                                satellites = None

                            _gps_latest.update({
                                "ts": now,
                                "lat": lat if lat is not None else _gps_latest.get("lat"),
                                "lon": lon if lon is not None else _gps_latest.get("lon"),
                                "altitude_m": alt,
                                "satellites": satellites,
                                "ok": True,
                                "error": None,
                            })
                            db_insert_gps(now, _gps_latest.get("lat"), _gps_latest.get("lon"),
                                          _gps_latest.get("speed_kmh"), _gps_latest.get("course"), alt)

                    except serial.SerialTimeoutException:
                        # Timeout is normal, continue polling
                        continue
                    except Exception as e:
                        _gps_latest["ok"] = False
                        _gps_latest["error"] = f"Serial read error: {e}"
                        time.sleep(1)
                        continue

        except Exception as e:
            _gps_latest["ok"] = False
            _gps_latest["error"] = f"GPS read error: {e}"
            time.sleep(2)


# =========================
# Startup
# =========================

def boot_failsafe_all_relays_off() -> None:
    """
    Boot failsafe: Immediately set all enabled relays to OFF before any rules run.
    This prevents relays from staying ON due to previous hardware state or floating inputs during boot.
    """
    print("[Startup] Boot failsafe: Setting all relays to OFF...")
    relays = db_list_relay_devices()
    
    for relay in relays:
        if not relay.get("is_enabled", True):
            continue
        
        pin = relay.get("pin")
        relay_name = relay.get("name", "unknown")
        active_low = bool(relay.get("active_low", 0))
        
        if pin is None:
            print(f"[Startup] Boot failsafe: Skipping relay {relay_name} (no pin configured)")
            continue
        
        try:
            # Force OFF immediately using direct pinctrl (bypasses DB and rate limiting)
            result = apply_relay_hardware_direct(pin, "off", active_low)
            if result.get("ok"):
                print(f"[Startup] Boot failsafe: Set relay {relay_name} (pin {pin}) to OFF")
            else:
                print(f"[Startup] Boot failsafe: Failed to set relay {relay_name} (pin {pin}) to OFF: {result.get('message')}")
        except Exception as e:
            print(f"[Startup] Boot failsafe: Exception setting relay {relay_name} (pin {pin}) to OFF: {e}")


def reconcile_all_relays_on_startup() -> None:
    """
    Startup reconciliation: Apply desired_state from relay_state_new to hardware.
    This ensures hardware matches the database state after reboot.
    On startup, we always apply the desired_state (computed from AUTO+rules or MANUAL override).
    If no rules match and mode=AUTO, desired_state will be OFF (from evaluate_rules).
    """
    print("[Startup] Reconciling all relays from relay_state_new (single source of truth)...")
    relays = db_list_relay_devices()
    
    for relay in relays:
        if not relay.get("is_enabled", True):
            print(f"[Startup] Skipping disabled relay {relay.get('name', 'unknown')}")
            continue
        
        relay_id = relay["id"]
        relay_name = relay.get("name", "unknown")
        
        try:
            # Force reconciliation (bypass rate limiting on startup)
            # This will compute desired_state from mode (AUTO+rules or MANUAL) and apply to hardware
            changed = reconcile_relay(relay_id, force=True)
            if changed:
                print(f"[Startup] Applied hardware state for relay {relay_name} ({relay_id})")
            else:
                print(f"[Startup] Relay {relay_name} ({relay_id}) already in correct state")
        except Exception as e:
            print(f"[Startup] Error reconciling relay {relay_name} ({relay_id}): {e}")
            import traceback
            traceback.print_exc()


def evaluate_rules_on_startup() -> None:
    """
    After startup reconciliation, explicitly evaluate rules for all AUTO mode relays.
    This ensures that if rules are enabled and conditions are already TRUE at boot,
    the relay will transition to ON immediately rather than waiting for sensor events.
    """
    print("[Startup] Evaluating rules for AUTO mode relays...")
    relays = db_list_relay_devices()
    
    for relay in relays:
        if not relay.get("is_enabled", True):
            continue
        
        relay_id = relay["id"]
        relay_name = relay.get("name", "unknown")
        
        # Get relay state to check mode
        relay_state = db_get_relay_state_new(relay_id)
        if not relay_state:
            continue
        
        mode = relay_state.get("mode", "auto")
        
        # Only evaluate rules for AUTO mode relays
        if mode != "auto":
            continue
        
        print(f"[Startup] Evaluating rules for relay {relay_name} (id={relay_id})...")
        
        try:
            # Force reconciliation which will evaluate rules and apply if conditions match
            # This bypasses rate limiting and ensures immediate evaluation
            changed = reconcile_relay(relay_id, force=True)
            if changed:
                # Get updated state to see what happened
                updated_state = db_get_relay_state_new(relay_id)
                desired = updated_state.get("desired_state", "unknown") if updated_state else "unknown"
                actual = updated_state.get("actual_state", "unknown") if updated_state else "unknown"
                print(f"[Startup] Rule matched → applied {desired} to relay {relay_name} (actual: {actual})")
            else:
                print(f"[Startup] No rule matched or relay {relay_name} already in correct state")
        except Exception as e:
            print(f"[Startup] Error evaluating rules for relay {relay_name} ({relay_id}): {e}")
            import traceback
            traceback.print_exc()


@app.on_event("startup")
def on_startup() -> None:
    db_init()
    # Step 1: Boot failsafe - immediately set all relays to OFF (before rules run)
    boot_failsafe_all_relays_off()
    # Step 2: Reconcile all relays from relay_state_new (single source of truth)
    # This will apply correct state based on AUTO+rules or MANUAL mode
    reconcile_all_relays_on_startup()
    # Step 3: Explicitly evaluate rules for AUTO mode relays
    # This ensures rules with conditions already TRUE at boot will trigger immediately
    evaluate_rules_on_startup()
    # Start GPS reader thread
    t_gps = threading.Thread(target=_gps_reader_thread, daemon=True)
    t_gps.start()
    # Start DHT22 poller thread (for legacy API compatibility)
    t_dht = threading.Thread(target=_dht22_poller_thread, daemon=True)
    t_dht.start()
    # Start sensor sampler thread (for snapshot system)
    t_sampler = threading.Thread(target=_sensor_sampler_thread, daemon=True)
    t_sampler.start()
    # Start rule evaluator thread
    t_rules = threading.Thread(target=_rule_evaluator_thread, daemon=True)
    t_rules.start()


# =========================
# Auth routes
# =========================

@app.post("/login")
def login(request: Request, username: str = Form(...), password: str = Form(...)):
    if username == SMARTIFY_USERNAME and password == SMARTIFY_PASSWORD:
        request.session["logged_in"] = True
        request.session["user"] = username
        return JSONResponse({"ok": True})
    return JSONResponse({"ok": False, "error": "invalid_credentials"}, status_code=401)


@app.post("/logout")
def logout(request: Request):
    request.session.clear()
    return JSONResponse({"ok": True})


@app.get("/api/me")
def api_me(request: Request, x_api_key: Optional[str] = Header(default=None, alias="X-API-Key")):
    authed = is_authenticated(request, x_api_key)
    return JSONResponse({
        "authenticated": authed,
        "user": request.session.get("user") if authed else None,
        "require_auth": SMARTIFY_REQUIRE_AUTH,
        "api_key_enabled": bool(SMARTIFY_API_KEY),
        "trusted_localhost": SMARTIFY_TRUST_LOCALHOST,
    })


# =========================
# API: Temperature
# =========================

@app.get("/api/temperature/latest")
def api_temperature_latest(request: Request, x_api_key: Optional[str] = Header(default=None, alias="X-API-Key")):
    """Return RAW latest sensor readings (for UI/graphs). Old behavior preserved."""
    err = require_auth(request, x_api_key)
    if err:
        return err
    # Return cached raw values immediately (no blocking sensor reads)
    return JSONResponse(_temp_latest)


@app.get("/api/temperature/snapshot/latest")
def api_temperature_snapshot_latest(request: Request, x_api_key: Optional[str] = Header(default=None, alias="X-API-Key")):
    """Return snapshot data (1-minute averages) for relay/rule engine use."""
    err = require_auth(request, x_api_key)
    if err:
        return err
    
    # Return snapshot data for each sensor
    kombi_snapshot = get_sensor_snapshot("kombi")
    garaza_snapshot = get_sensor_snapshot("garaza")
    
    # Build response with snapshot data
    sensors = []
    for idx, sensor_name in enumerate(["kombi", "garaza"]):
        snapshot = kombi_snapshot if sensor_name == "kombi" else garaza_snapshot
        sensors.append({
            "sensor_index": idx,
            "sensor_name": sensor_name,
            "avg_temp": snapshot.get("avg_temp"),
            "avg_humidity": snapshot.get("avg_humidity"),
            "sample_count": snapshot.get("sample_count"),
            "updated_at": snapshot.get("updated_at"),
            "last_good_at": snapshot.get("last_good_at"),
            "age_seconds": snapshot.get("age_seconds"),
            "is_stale": snapshot.get("is_stale"),
            "is_ready": snapshot.get("is_ready"),
        })
    
    return JSONResponse({
        "ts": int(time.time()),
        "sensors": sensors,
    })


@app.get("/api/temperature/history")
def api_temperature_history(
    request: Request,
    range: str = "day",
    sensor: Optional[int] = None,
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
):
    err = require_auth(request, x_api_key)
    if err:
        return err

    now = int(time.time())
    # Determine time window
    if range == "hour":
        since = now - 3600
        bucket_seconds = 300  # 5 minutes
    elif range == "day":
        since = now - 86400
        bucket_seconds = 300  # 5 minutes
    elif range == "week":
        since = now - 7 * 86400
        bucket_seconds = 1800  # 30 minutes
    elif range == "month":
        since = now - 30 * 86400
        bucket_seconds = 7200  # 2 hours
    elif range == "year":
        since = now - 365 * 86400
        bucket_seconds = 86400  # 1 day
    else:
        return JSONResponse({"error": "invalid_range", "allowed": ["hour", "day", "week", "month", "year"]}, status_code=400)

    # Get all raw rows
    raw_rows = db_query_temp_since(since, sensor_index=sensor)
    
    # Bucket/aggregate data by time window
    buckets: Dict[int, Dict[int, List[float]]] = {}  # bucket_ts -> sensor_index -> [temps]
    
    for row in raw_rows:
        ts = row["ts"]
        sensor_idx = row["sensor_index"]
        temp = row["temperature_c"]
        
        if temp is None:
            continue
        
        # Calculate bucket timestamp (round down to bucket boundary)
        bucket_ts = (ts // bucket_seconds) * bucket_seconds
        
        if bucket_ts not in buckets:
            buckets[bucket_ts] = {}
        if sensor_idx not in buckets[bucket_ts]:
            buckets[bucket_ts][sensor_idx] = []
        
        buckets[bucket_ts][sensor_idx].append(temp)
    
    # Convert buckets to rows (average temperatures per bucket)
    # Group by bucket_ts and include both sensors
    aggregated_rows = []
    for bucket_ts in sorted(buckets.keys()):
        sensor_data = buckets[bucket_ts]
        # Ensure we have entries for both sensors (0 and 1) if they exist
        for sensor_idx in [0, 1]:
            if sensor_idx in sensor_data:
                temps = sensor_data[sensor_idx]
                avg_temp = sum(temps) / len(temps) if temps else None
                aggregated_rows.append({
                    "ts": bucket_ts,
                    "sensor_index": sensor_idx,
                    "temperature_c": avg_temp,
                    "humidity": None,  # We're only aggregating temperature for now
                })
    
    return JSONResponse({
        "since": since,
        "now": now,
        "rows": aggregated_rows,
        "bucket_seconds": bucket_seconds,
    })


# =========================
# API: GPS
# =========================

@app.get("/api/gps/current")
def api_gps_current(request: Request, x_api_key: Optional[str] = Header(default=None, alias="X-API-Key")):
    err = require_auth(request, x_api_key)
    if err:
        return err
    return JSONResponse(_gps_latest)


@app.get("/api/gps/track")
def api_gps_track(
    request: Request,
    hours: Optional[int] = None,
    minutes: Optional[int] = None,
    limit: int = 2000,
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
):
    err = require_auth(request, x_api_key)
    if err:
        return err

    now = int(time.time())
    if minutes is not None:
        since = now - int(minutes) * 60
    elif hours is not None:
        since = now - int(hours) * 3600
    else:
        since = now - 24 * 3600

    limit = max(1, min(int(limit), 50000))
    rows = db_query_gps_since(since, limit=limit)
    return JSONResponse({"since": since, "now": now, "rows": rows})


# =========================
# Relay Automation Engine
# =========================

RULE_EVAL_INTERVAL = 5  # Evaluate rules every 5 seconds


def get_sensor_snapshot(sensor_name: str) -> Dict[str, Any]:
    """
    Get sensor snapshot with stale detection.
    Returns: value, updated_at, last_good_at, is_stale, age_seconds, is_ready
    """
    now = int(time.time())
    snapshot = db_get_sensor_snapshot(sensor_name)
    
    if not snapshot:
        return {
            "sensor_name": sensor_name,
            "avg_temp": None,
            "avg_humidity": None,
            "sample_count": 0,
            "updated_at": None,
            "last_good_at": None,
            "is_stale": True,
            "age_seconds": None,
            "is_ready": False,
        }
    
    last_good_at = snapshot.get("last_good_at", 0)
    updated_at = snapshot.get("updated_at", 0)
    sample_count = snapshot.get("sample_count", 0)
    age_seconds = now - last_good_at if last_good_at else None
    
    # Stale if no valid samples for 10 minutes
    is_stale = age_seconds is not None and age_seconds > SENSOR_STALE_THRESHOLD
    
    # Ready if we have at least N samples (warmup requirement)
    is_ready = sample_count >= SENSOR_WARMUP_SAMPLES
    
    return {
        "sensor_name": sensor_name,
        "avg_temp": snapshot.get("avg_temp"),
        "avg_humidity": snapshot.get("avg_humidity"),
        "sample_count": sample_count,
        "updated_at": updated_at,
        "last_good_at": last_good_at,
        "is_stale": is_stale,
        "age_seconds": age_seconds,
        "is_ready": is_ready,
    }

def _evaluate_temperature_condition(condition: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
    """
    Evaluate a temperature condition using snapshot data.
    Returns: (result: bool, reason: Optional[str])
    If sensor is stale or not ready, returns (False, reason) to force OFF.
    """
    if condition.get("type") != "temperature":
        return (False, f"Condition type mismatch: {condition.get('type')} != 'temperature'")
    
    sensor_name = condition.get("sensor", "")
    operator = condition.get("operator", "")
    value = condition.get("value")
    uses_snapshot = condition.get("uses_snapshot", True)  # Default to True for new rules
    
    if value is None:
        return (False, "Condition value is None")
    
    if not sensor_name:
        return (False, "Sensor name not specified")
    
    # Get snapshot (always use snapshot, never raw sensor reads)
    snapshot = get_sensor_snapshot(sensor_name)
    
    # Check if sensor is stale (no valid samples for 10 minutes)
    if snapshot.get("is_stale"):
        age_min = snapshot.get("age_seconds", 0) // 60
        return (False, f"sensor_stale(>{age_min}m)")
    
    # Check if sensor is not ready (warmup period)
    if not snapshot.get("is_ready"):
        sample_count = snapshot.get("sample_count", 0)
        return (False, f"sensor_warming_up({sample_count}/{SENSOR_WARMUP_SAMPLES} samples)")
    
    # Get temperature from snapshot
    temp = snapshot.get("avg_temp")
    if temp is None:
        return (False, f"sensor_no_data")
    
    # Evaluate condition
    if operator == "below":
        result = temp < value
    elif operator == "above":
        result = temp > value
    else:
        return (False, f"Invalid operator: {operator}")
    
    print(f"[Rule Engine] Evaluating snapshot {sensor_name}: {temp:.1f}°C {operator} {value}°C = {result}")
    return (result, None)


def evaluate_rules(relay_id: str, temp_data: Optional[Dict[str, Any]] = None, current_state: Optional[str] = None) -> Tuple[Optional[str], Optional[Dict[str, Any]], bool, Optional[str]]:
    """
    Deterministically evaluate enabled rules for a relay using snapshot data.
    Returns (desired_state, matched_rule, sensor_data_available, reason) tuple.
    desired_state is "on" or "off" based on first matching rule, or None if sensor data unavailable.
    matched_rule is the rule dict that matched, or None if no rule matched.
    sensor_data_available is False if sensor data is unavailable (should preserve current state).
    reason is a string explaining why state was set (e.g., "sensor_stale", "sensor_warming_up").
    
    Cooldown only prevents triggering a state CHANGE, not maintaining the current state.
    """
    rules = db_list_relay_rules(relay_id)
    enabled_rules = [r for r in rules if r.get("is_enabled", True)]
    
    if not enabled_rules:
        return ("off", None, True, "no_rules")  # No enabled rules -> default to off
    
    # Sort by priority (lower number = higher priority), then by creation time
    enabled_rules.sort(key=lambda x: (x.get("priority", 100), x.get("created_at", 0)))
    
    # Evaluate each rule in priority order
    now = int(time.time())
    for rule in enabled_rules:
        # Evaluate condition using snapshot (not raw temp_data)
        condition = rule.get("condition", {})
        condition_result, reason = _evaluate_temperature_condition(condition)
        
        # If condition evaluation failed due to sensor issues (stale/warming), force OFF
        if not condition_result and reason and ("sensor_stale" in reason or "sensor_warming_up" in reason or "sensor_no_data" in reason):
            print(f"[Rule Engine] Sensor issue for rule '{rule.get('name')}': {reason}")
            return ("off", None, False, reason)
        
        # If condition doesn't match, continue to next rule
        if not condition_result:
            continue
        
        # Condition matches - determine desired state
        action = rule.get("action", "")
        rule_desired_state = None
        if action == "turn_on":
            rule_desired_state = "on"
        elif action == "turn_off":
            rule_desired_state = "off"
        else:
            continue  # Invalid action
        
        # Check cooldown only if this rule would CHANGE the state
        # If it would maintain current state, cooldown doesn't apply
        if current_state is not None and rule_desired_state == current_state:
            # Rule wants same state as current - cooldown doesn't apply, rule matches
            return (rule_desired_state, rule, True, None)
        
        # Rule would change state - check cooldown
        last_triggered = rule.get("last_triggered_at")
        if last_triggered:
            age = now - last_triggered
            cooldown_sec = rule.get("cooldown_seconds", 60)
            if age < cooldown_sec:
                # Still in cooldown and would change state - skip this rule
                continue
        
        # Rule matches and either no cooldown or cooldown expired - first match wins
        return (rule_desired_state, rule, True, None)
    
    # No rule matched -> default to off
    return ("off", None, True, "no_match")


def reconcile_relay(relay_id: str, force: bool = False) -> bool:
    """
    Core state machine: Reconcile desired state with actual hardware state.
    
    This is the single source of truth for relay state:
    1. Determines desired_state based on mode (auto/manual) and rules
    2. Compares desired_state with actual_state
    3. If different, applies hardware command and updates actual_state
    
    Args:
        relay_id: Relay device ID
        force: If True, bypass rate limiting (2s cooldown)
    
    Returns:
        True if hardware state was changed, False otherwise
    """
    now = int(time.time())
    
    # Get current relay state
    relay_state = db_get_relay_state_new(relay_id)
    if not relay_state:
        print(f"[Reconcile] Relay {relay_id} not found")
        return False
    
    device = db_get_relay_device(relay_id)
    if not device:
        print(f"[Reconcile] Relay device {relay_id} not found")
        return False
    
    mode = relay_state.get("mode", "auto")
    current_actual = relay_state.get("actual_state") or relay_state.get("state", "off")
    current_desired = relay_state.get("desired_state")
    last_applied = relay_state.get("last_applied_at", 0)
    manual_until = relay_state.get("manual_until")
    
    # Step 1: Handle manual mode expiration
    if mode == "manual" and manual_until is not None:
        if now > manual_until:
            # Manual mode expired, switch to auto
            print(f"[Reconcile] Manual mode expired for relay {relay_id}, switching to auto")
            db_update_relay_state_new(relay_id, mode="auto")
            mode = "auto"
    
    # Step 2: Determine desired_state
    if mode == "manual":
        # Manual mode: desired_state = manual_state
        desired_state = relay_state.get("manual_state")
        if desired_state not in ("on", "off"):
            desired_state = current_actual  # Fallback to current state
        source = "manual"
        reason = "Manual override"
    else:
        # Auto mode: evaluate rules using snapshot (not raw temp_data)
        # Pass current_actual to evaluate_rules so cooldown only applies to state changes
        desired_state_result, matched_rule, sensor_data_available, reason_str = evaluate_rules(relay_id, None, current_actual)
        
        if not sensor_data_available:
            # Sensor data unavailable (stale/warming) - force OFF
            print(f"[Reconcile] Sensor data unavailable ({reason_str}), forcing OFF")
            desired_state = "off"
            source = "rule"
            reason = f"Sensor unavailable: {reason_str}"
            matched_rule = None
        else:
            # Sensor data available - use the result
            desired_state = desired_state_result
            source = "rule"
            if matched_rule:
                # Build reason string using snapshot data
                condition = matched_rule.get("condition", {})
                sensor_name = condition.get("sensor", "")
                operator = condition.get("operator", "")
                value = condition.get("value")
                snapshot = get_sensor_snapshot(sensor_name)
                temp = snapshot.get("avg_temp")
                if temp is not None:
                    reason = f"Rule '{matched_rule.get('name')}': {sensor_name.capitalize()} temp {operator} {value}°C (snapshot: {temp:.1f}°C)"
                else:
                    reason = f"Rule '{matched_rule.get('name')}' matched"
            else:
                reason = reason_str or "No rule matched, default to off"
    
    # Step 3: Update desired_state in database (only if it changed)
    if desired_state is not None and desired_state != current_desired:
        db_update_relay_state_new(relay_id, desired_state=desired_state)
        print(f"[Reconcile] Updated desired_state for relay {relay_id}: {current_desired} -> {desired_state} ({reason})")
    elif desired_state is None:
        # desired_state is None means sensor data unavailable - use current_desired
        desired_state = current_desired
        print(f"[Reconcile] Sensor data unavailable, preserving desired_state for relay {relay_id}: {current_desired} ({reason})")
    
    # Step 4: Check if hardware needs to be updated
    if desired_state == current_actual:
        # Already in desired state, nothing to do
        return False
    
    # Step 5: Rate limiting - avoid flapping
    if not force and (now - last_applied) < 2:
        print(f"[Reconcile] Rate limit: last_applied {now - last_applied}s ago, skipping hardware update")
        return False
    
    # Step 6: Apply hardware command using pinctrl
    relay_name = device.get("name", "unknown")
    pin = device.get("pin")
    print(f"[Reconcile] Applying hardware: relay {relay_name} (id={relay_id}, pin={pin}) {current_actual} -> {desired_state} (source: {source}, reason: {reason})")
    
    # Use new pin-based hardware apply function
    result = apply_relay_hardware(relay_id, desired_state)
    
    if result.get("ok"):
        # Success: update actual_state
        db_update_relay_state_new(
            relay_id,
            actual_state=desired_state,
            last_applied_at=now
        )
        
        # Update rule's last_triggered_at only if we actually changed hardware state
        # (cooldown was already checked in evaluate_rules, but we only update timestamp on actual state change)
        if matched_rule:
            db_update_rule_last_triggered(matched_rule["id"])
        
        # Log event (always log hardware applies, including startup)
        rule_id = matched_rule.get("id") if matched_rule else None
        db_log_relay_event(
            relay_id,
            source,
            current_actual,
            desired_state,
            reason,
            rule_id
        )
        
        print(f"[Reconcile] Successfully updated relay {relay_name} (id={relay_id}, pin={pin}) to {desired_state} (source: {source}, reason: {reason})")
        return True
    else:
        # Hardware apply failed
        error_msg = result.get("message", result.get("error", "Unknown error"))
        print(f"[Reconcile] Failed to apply hardware: {error_msg}")
        db_log_relay_event(
            relay_id,
            source,
            current_actual,
            current_actual,  # State didn't change
            f"Hardware apply failed: {error_msg}",
            None
        )
        return False


def _evaluate_relay_rules() -> None:
    """
    Background thread: Reconcile all relays periodically.
    This ensures desired_state stays in sync with actual_state.
    """
    try:
        # Get all enabled relay devices
        relays = db_list_relay_devices()
        
        for relay in relays:
            if not relay.get("is_enabled", True):
                continue
            
            relay_id = relay["id"]
            try:
                reconcile_relay(relay_id, force=False)
            except Exception as e:
                print(f"[Rule Engine] Error reconciling relay {relay_id}: {e}")
    
    except Exception as e:
        # Log error but don't crash
        print(f"[Rule Engine] Error: {e}")
        import traceback
        traceback.print_exc()


def _rule_evaluator_thread() -> None:
    """Background thread that evaluates rules periodically."""
    while True:
        try:
            _evaluate_relay_rules()
        except Exception as e:
            print(f"[Rule Evaluator] Error: {e}")
        time.sleep(RULE_EVAL_INTERVAL)


# =========================
# Relay Control
# =========================

_relay_lock = threading.Lock()
HEADER_RELAY_NAME = "header"
HEADER_RELAY_PIN = 27  # Legacy constant, actual pin comes from DB


# DEPRECATED: _set_relay_state and _init_relay_state removed
# All relay control now goes through reconcile_relay() which uses relay_state_new as single source of truth


def apply_relay_hardware_direct(pin: int, desired_state: str, active_low: bool = False) -> Dict[str, Any]:
    """
    Apply desired_state directly to GPIO pin using pinctrl (bypasses DB lookup).
    Used for boot failsafe to force OFF state.
    
    Args:
        pin: GPIO pin number
        desired_state: "on" or "off"
        active_low: True if relay is active_low, False for active_high
    
    Returns:
        Dict with ok, error, message fields
    """
    if desired_state not in ("on", "off"):
        return {"ok": False, "error": "invalid_state", "message": "desired_state must be 'on' or 'off'"}
    
    # Determine pinctrl command based on desired_state and active_low
    # active_high (active_low=0): dh=on, dl=off
    # active_low (active_low=1): dh=off, dl=on
    if desired_state == "on":
        pinctrl_op = "dl" if active_low else "dh"  # active_low: dl=on, active_high: dh=on
    else:
        pinctrl_op = "dh" if active_low else "dl"  # active_low: dh=off, active_high: dl=off
    
    cmd = ["sudo", "pinctrl", "set", str(pin), "op", pinctrl_op]
    cmd_str = " ".join(cmd)
    
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=5,
        )
        
        if proc.returncode == 0:
            return {"ok": True, "state": desired_state, "pin": pin, "command": cmd_str}
        else:
            error_msg = proc.stderr.strip() or f"Command failed with code {proc.returncode}"
            return {"ok": False, "error": "command_failed", "message": error_msg}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "timeout", "message": "pinctrl command timed out"}
    except Exception as e:
        return {"ok": False, "error": "exception", "message": str(e)}


def apply_relay_hardware(relay_id: str, desired_state: str) -> Dict[str, Any]:
    """
    Apply desired_state to relay hardware using pinctrl.
    
    Args:
        relay_id: Relay device ID
        desired_state: "on" or "off"
    
    Returns:
        Dict with ok, error, message fields
    """
    if desired_state not in ("on", "off"):
        return {"ok": False, "error": "invalid_state", "message": "desired_state must be 'on' or 'off'"}
    
    # Get relay device info
    device = db_get_relay_device(relay_id)
    if not device:
        return {"ok": False, "error": "not_found", "message": f"Relay device {relay_id} not found"}
    
    pin = device.get("pin")
    relay_name = device.get("name", "unknown")
    active_low = bool(device.get("active_low", 0))
    
    if pin is None:
        return {"ok": False, "error": "no_pin", "message": f"Relay {relay_id} has no pin configured"}
    
    # Determine pinctrl command based on desired_state and active_low
    # active_high (active_low=0): dh=on, dl=off
    # active_low (active_low=1): dh=off, dl=on
    if desired_state == "on":
        pinctrl_op = "dl" if active_low else "dh"  # active_low: dl=on, active_high: dh=on
    else:
        pinctrl_op = "dh" if active_low else "dl"  # active_low: dh=off, active_high: dl=off
    
    cmd = ["sudo", "pinctrl", "set", str(pin), "op", pinctrl_op]
    cmd_str = " ".join(cmd)
    
    print(f"[Hardware] Applying relay {relay_name} (id={relay_id}, pin={pin}): desired_state={desired_state}, active_low={active_low}, command={cmd_str}")
    
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=5,
        )
        
        if proc.returncode == 0:
            print(f"[Hardware] Successfully applied {desired_state} to relay {relay_name} (pin {pin})")
            return {"ok": True, "state": desired_state, "pin": pin, "command": cmd_str}
        else:
            error_msg = proc.stderr.strip() or f"Command failed with code {proc.returncode}"
            print(f"[Hardware] Failed to apply {desired_state} to relay {relay_name} (pin {pin}): {error_msg}")
            return {"ok": False, "error": "command_failed", "message": error_msg}
    except subprocess.TimeoutExpired:
        error_msg = "pinctrl command timed out"
        print(f"[Hardware] {error_msg} for relay {relay_name} (pin {pin})")
        return {"ok": False, "error": "timeout", "message": error_msg}
    except Exception as e:
        error_msg = str(e)
        print(f"[Hardware] Exception applying {desired_state} to relay {relay_name} (pin {pin}): {error_msg}")
        return {"ok": False, "error": "exception", "message": error_msg}


# =========================
# API: Network (nmcli)
# =========================

def run_nmcli(args: List[str]) -> subprocess.CompletedProcess:
    cmd = ["nmcli"] + args
    return subprocess.run(cmd, capture_output=True, text=True)


@app.get("/api/network/status")
def api_network_status(request: Request, x_api_key: Optional[str] = Header(default=None, alias="X-API-Key")):
    err = require_auth(request, x_api_key)
    if err:
        return err

    proc = run_nmcli(["-t", "-f", "ACTIVE,SSID,DEVICE", "dev", "wifi"])
    if proc.returncode != 0:
        return JSONResponse({"error": "nmcli_failed", "stderr": proc.stderr.strip()}, status_code=500)

    lines = [l.strip() for l in proc.stdout.splitlines() if l.strip()]
    return JSONResponse({"rows": lines})


@app.get("/api/network/scan")
def api_network_scan(request: Request, x_api_key: Optional[str] = Header(default=None, alias="X-API-Key")):
    err = require_auth(request, x_api_key)
    if err:
        return err

    proc = run_nmcli(["-t", "-f", "SSID,SIGNAL,SECURITY", "dev", "wifi", "list"])
    if proc.returncode != 0:
        return JSONResponse({"error": "nmcli_failed", "stderr": proc.stderr.strip()}, status_code=500)

    rows = []
    for line in proc.stdout.splitlines():
        if not line.strip():
            continue
        parts = line.split(":")
        ssid = parts[0] if len(parts) > 0 else ""
        signal = parts[1] if len(parts) > 1 else ""
        security = parts[2] if len(parts) > 2 else ""
        rows.append({"ssid": ssid, "signal": signal, "security": security})

    return JSONResponse({"networks": rows})


# =========================
# API: Relay Automation
# =========================

def _get_relay_pending_state(relay_id: str) -> Dict[str, Any]:
    """
    Determine if relay is in a pending/transitional state (cooldown, reconciling, startup, sensor issues).
    Returns dict with pending status, reason, and cooldown info.
    """
    now = int(time.time())
    pending = False
    reason = None
    cooldown_remaining = None
    source = None
    
    # Get relay state
    relay_state = db_get_relay_state_new(relay_id)
    if not relay_state:
        # State not found - could be during startup
        return {
            "pending": True,
            "reason": "startup",
            "cooldown_remaining": None,
            "source": "startup"
        }
    
    actual_state = relay_state.get("actual_state")
    desired_state = relay_state.get("desired_state")
    last_applied_at = relay_state.get("last_applied_at", 0)
    mode = relay_state.get("mode", "auto")
    
    # Check if actual_state is unknown (startup/reconciling)
    if actual_state is None or actual_state == "":
        pending = True
        reason = "reconciling"
        source = "startup" if last_applied_at == 0 else "rule"
    
    # Check if desired_state differs from actual_state (reconciling)
    elif desired_state and desired_state != actual_state:
        pending = True
        reason = "reconciling"
        source = mode  # "manual" or "rule"
    
    # Check sensor status for AUTO mode relays (if rules depend on sensors)
    if mode == "auto" and not pending:
        rules = db_list_relay_rules(relay_id)
        enabled_rules = [r for r in rules if r.get("is_enabled", True)]
        
        # Check if any rule depends on a sensor that is stale or warming up
        for rule in enabled_rules:
            condition = rule.get("condition", {})
            if condition.get("type") == "temperature":
                sensor_name = condition.get("sensor", "")
                if sensor_name:
                    snapshot = get_sensor_snapshot(sensor_name)
                    if snapshot.get("is_stale"):
                        pending = True
                        age_min = snapshot.get("age_seconds", 0) // 60
                        reason = f"sensor_stale"
                        source = "sensor"
                        break
                    elif not snapshot.get("is_ready"):
                        pending = True
                        reason = f"sensor_warming_up"
                        source = "sensor"
                        break
        
        # Check cooldown (only if sensor is OK)
        if not pending:
            for rule in enabled_rules:
                last_triggered = rule.get("last_triggered_at")
                if last_triggered:
                    age = now - last_triggered
                    cooldown_sec = rule.get("cooldown_seconds", 60)
                    if age < cooldown_sec:
                        pending = True
                        reason = "cooldown"
                        cooldown_remaining = cooldown_sec - age
                        source = "rule"
                        break
    
    return {
        "pending": pending,
        "reason": reason,
        "cooldown_remaining": cooldown_remaining,
        "source": source or mode
    }

@app.get("/api/relays")
def api_relays_list(request: Request, x_api_key: Optional[str] = Header(default=None, alias="X-API-Key")):
    """List all relays with their current state and mode."""
    err = require_auth(request, x_api_key)
    if err:
        return err
    
    try:
        relays = db_list_relay_devices()
        result = []
        for relay in relays:
            relay_id = relay["id"]
            state = db_get_relay_state_new(relay_id)
            # During startup race conditions, if hardware state is unknown, return desired_state
            # This prevents 500 errors when API is called before hardware is fully initialized
            if state:
                # Prefer actual_state, fallback to desired_state, then state field, then "off"
                hardware_state = state.get("actual_state") or state.get("desired_state") or state.get("state", "off")
            else:
                hardware_state = "off"  # Safe default if state not found
            
            result.append({
                "id": relay_id,
                "name": relay["name"],
                "pin": relay["pin"],
                "active_low": bool(relay.get("active_low", 0)),
                "state": hardware_state,
                "mode": state.get("mode", "auto") if state else "auto",
                "manual_until": state.get("manual_until") if state else None,
                "updated_at": state.get("updated_at") if state else None,
                "is_enabled": bool(relay.get("is_enabled", True)),
            })
        
        return JSONResponse({"ok": True, "relays": result})
    except Exception as e:
        # NEVER return 500 - always return valid JSON with safe fallback
        print(f"[API] Error listing relays: {e}")
        import traceback
        traceback.print_exc()
        return JSONResponse({"ok": True, "relays": [], "error": "Failed to list relays"})


@app.get("/api/relays/{relay_id}")
def api_relay_get(relay_id: str, request: Request, x_api_key: Optional[str] = Header(default=None, alias="X-API-Key")):
    """Get relay details with pending state information. NEVER returns 500."""
    err = require_auth(request, x_api_key)
    if err:
        return err
    
    try:
        relay = db_get_relay_device(relay_id)
        if not relay:
            # Return safe fallback instead of 404
            return JSONResponse({
                "ok": True,
                "relay": {
                    "id": relay_id,
                    "name": "unknown",
                    "pin": None,
                    "active_low": False,
                    "is_enabled": False,
                    "state": "off",
                    "mode": "auto",
                    "pending": True,
                    "reason": "not_found",
                    "cooldown_remaining": None,
                    "source": "system"
                }
            })
        
        state = db_get_relay_state_new(relay_id)
        
        # Get pending state info
        pending_info = _get_relay_pending_state(relay_id)
        
        # Determine hardware state with fallback chain
        if state:
            hardware_state = state.get("actual_state") or state.get("desired_state") or state.get("state", "off")
        else:
            hardware_state = "off"  # Safe default
        
        return JSONResponse({
            "ok": True,
            "relay": {
                "id": relay["id"],
                "name": relay["name"],
                "pin": relay["pin"],
                "active_low": bool(relay.get("active_low", 0)),
                "is_enabled": bool(relay.get("is_enabled", True)),
                "state": hardware_state,
                "mode": state.get("mode", "auto") if state else "auto",
                "manual_until": state.get("manual_until") if state else None,
                "updated_at": state.get("updated_at") if state else None,
                "pending": pending_info["pending"],
                "reason": pending_info["reason"],
                "cooldown_remaining": pending_info["cooldown_remaining"],
                "source": pending_info["source"]
            },
        })
    except Exception as e:
        # NEVER return 500 - always return valid JSON with safe fallback
        print(f"[API] Error getting relay {relay_id}: {e}")
        import traceback
        traceback.print_exc()
        return JSONResponse({
            "ok": True,
            "relay": {
                "id": relay_id,
                "name": "unknown",
                "pin": None,
                "active_low": False,
                "is_enabled": False,
                "state": "off",
                "mode": "auto",
                "pending": True,
                "reason": "error",
                "cooldown_remaining": None,
                "source": "system"
            }
        })


@app.post("/api/relays/{relay_id}/state")
def api_relay_set_state(
    relay_id: str,
    request: Request,
    body: Dict[str, Any] = Body(...),
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
):
    """Set relay state manually. Sets mode to 'manual' and uses reconcile to apply. NEVER returns 500."""
    err = require_auth(request, x_api_key)
    if err:
        return err
    
    try:
        # Check if relay is in pending state (cooldown/reconciling)
        pending_info = _get_relay_pending_state(relay_id)
        if pending_info["pending"]:
            # Return error response but with HTTP 200 (never 500)
            reason_msg = pending_info["reason"]
            if reason_msg == "cooldown":
                cooldown_msg = f" ({pending_info['cooldown_remaining']}s remaining)" if pending_info["cooldown_remaining"] else ""
                error_msg = f"Relay is in cooldown period{cooldown_msg}"
            elif reason_msg == "reconciling":
                error_msg = "Relay state is being synchronized"
            elif reason_msg == "startup":
                error_msg = "Relay is initializing after startup"
            else:
                error_msg = f"Relay is in {reason_msg} state"
            
            # Get current state for response
            relay_state = db_get_relay_state_new(relay_id)
            current_state = "off"
            if relay_state:
                current_state = relay_state.get("actual_state") or relay_state.get("desired_state") or relay_state.get("state", "off")
            
            return JSONResponse({
                "ok": False,
                "error": "pending",
                "message": error_msg,
                "state": current_state,
                "pending": True,
                "reason": pending_info["reason"],
                "cooldown_remaining": pending_info["cooldown_remaining"],
                "source": pending_info["source"]
            })
        
        relay = db_get_relay_device(relay_id)
        if not relay:
            return JSONResponse({
                "ok": False,
                "error": "not_found",
                "message": "Relay device not found",
                "state": "off",
                "pending": False
            })
        
        state = body.get("state", "").strip().lower()
        if state not in ("on", "off"):
            return JSONResponse({
                "ok": False,
                "error": "invalid_state",
                "message": "State must be 'on' or 'off'",
                "state": "off",
                "pending": False
            })
        
        mode = body.get("mode", "manual")
        if mode not in ("auto", "manual"):
            mode = "manual"
        
        duration_seconds = body.get("durationSeconds")
        manual_until = None
        if mode == "manual" and duration_seconds:
            manual_until = int(time.time()) + int(duration_seconds)
        
        # Update database: set manual mode and manual_state, then reconcile
        db_update_relay_state_new(
            relay_id=relay_id,
            mode=mode,
            manual_state=state if mode == "manual" else None,
            manual_until=manual_until if mode == "manual" else None
        )
        
        # Reconcile will handle hardware command
        reconcile_relay(relay_id, force=True)
        
        # Get updated state for response
        updated_state = db_get_relay_state_new(relay_id)
        if updated_state:
            response_state = updated_state.get("actual_state") or updated_state.get("desired_state") or updated_state.get("state", "off")
        else:
            response_state = state
        
        # Get updated pending info
        updated_pending = _get_relay_pending_state(relay_id)
        
        return JSONResponse({
            "ok": True,
            "state": response_state,
            "mode": mode,
            "manual_until": manual_until,
            "pending": updated_pending["pending"],
            "reason": updated_pending["reason"],
            "cooldown_remaining": updated_pending["cooldown_remaining"],
            "source": updated_pending["source"]
        })
    except Exception as e:
        # NEVER return 500 - always return valid JSON with safe fallback
        print(f"[API] Error setting relay {relay_id} state: {e}")
        import traceback
        traceback.print_exc()
        
        # Try to get current state for fallback
        try:
            relay_state = db_get_relay_state_new(relay_id)
            fallback_state = "off"
            if relay_state:
                fallback_state = relay_state.get("actual_state") or relay_state.get("desired_state") or relay_state.get("state", "off")
        except:
            fallback_state = "off"
        
        return JSONResponse({
            "ok": False,
            "error": "exception",
            "message": "Failed to set relay state",
            "state": fallback_state,
            "pending": True,
            "reason": "error",
            "cooldown_remaining": None,
            "source": "system"
        })


@app.post("/api/relays/{relay_id}/auto")
def api_relay_set_auto(
    relay_id: str,
    request: Request,
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
):
    """Set relay mode to auto (resume automation). Clears manual fields and reconciles immediately."""
    err = require_auth(request, x_api_key)
    if err:
        return err
    
    relay = db_get_relay_device(relay_id)
    if not relay:
        return JSONResponse({"ok": False, "error": "not_found"}, status_code=404)
    
    # Switch to auto mode (will automatically clear manual fields)
    db_update_relay_state_new(relay_id=relay_id, mode="auto")
    
    # Immediately reconcile to apply rules
    reconcile_relay(relay_id, force=True)
    
    return JSONResponse({"ok": True, "mode": "auto"})


@app.get("/api/relays/{relay_id}/rules")
def api_relay_rules_list(
    relay_id: str,
    request: Request,
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
):
    """List rules for a relay."""
    err = require_auth(request, x_api_key)
    if err:
        return err
    
    rules = db_list_relay_rules(relay_id)
    return JSONResponse({"ok": True, "rules": rules})


@app.post("/api/relays/{relay_id}/rules")
def api_relay_rule_create(
    relay_id: str,
    request: Request,
    body: Dict[str, Any] = Body(...),
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
):
    """Create a new rule."""
    err = require_auth(request, x_api_key)
    if err:
        return err
    
    relay = db_get_relay_device(relay_id)
    if not relay:
        return JSONResponse({"ok": False, "error": "not_found"}, status_code=404)
    
    name = body.get("name", "").strip()
    if not name:
        return JSONResponse({"ok": False, "error": "name_required"}, status_code=400)
    
    condition = body.get("condition", {})
    action = body.get("action", "")
    if action not in ("turn_on", "turn_off"):
        return JSONResponse({"ok": False, "error": "invalid_action"}, status_code=400)
    
    priority = int(body.get("priority", 100))
    cooldown_seconds = int(body.get("cooldown_seconds", 60))
    is_enabled = body.get("is_enabled", True)
    
    if cooldown_seconds < 5:
        cooldown_seconds = 5
    
    rule_id = db_create_relay_rule(relay_id, name, condition, action, priority, cooldown_seconds, is_enabled)
    rule = db_get_relay_rule(rule_id)
    
    # Reconcile relay to apply new rule immediately
    reconcile_relay(relay_id, force=True)
    
    return JSONResponse({"ok": True, "rule": rule}, status_code=201)


@app.put("/api/rules/{rule_id}")
def api_rule_update(
    rule_id: str,
    request: Request,
    body: Dict[str, Any] = Body(...),
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
):
    """Update a rule."""
    err = require_auth(request, x_api_key)
    if err:
        return err
    
    rule = db_get_relay_rule(rule_id)
    if not rule:
        return JSONResponse({"ok": False, "error": "not_found"}, status_code=404)
    
    name = body.get("name")
    condition = body.get("condition")
    action = body.get("action")
    priority = body.get("priority")
    cooldown_seconds = body.get("cooldown_seconds")
    is_enabled = body.get("is_enabled")
    
    if action and action not in ("turn_on", "turn_off"):
        return JSONResponse({"ok": False, "error": "invalid_action"}, status_code=400)
    
    if cooldown_seconds is not None and cooldown_seconds < 5:
        cooldown_seconds = 5
    
    updated = db_update_relay_rule(rule_id, name, condition, action, priority, cooldown_seconds, is_enabled)
    if not updated:
        return JSONResponse({"ok": False, "error": "update_failed"}, status_code=400)
    
    rule = db_get_relay_rule(rule_id)
    relay_id = rule.get("relay_id") if rule else None
    if relay_id:
        # Reconcile relay to apply updated rule immediately
        reconcile_relay(relay_id, force=True)
    
    return JSONResponse({"ok": True, "rule": rule})


@app.delete("/api/rules/{rule_id}")
def api_rule_delete(
    rule_id: str,
    request: Request,
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
):
    """Delete a rule."""
    err = require_auth(request, x_api_key)
    if err:
        return err
    
    # Get relay_id before deleting
    rule = db_get_relay_rule(rule_id)
    relay_id = rule.get("relay_id") if rule else None
    
    deleted = db_delete_relay_rule(rule_id)
    if not deleted:
        return JSONResponse({"ok": False, "error": "not_found"}, status_code=404)
    
    if relay_id:
        # Reconcile relay to apply deletion immediately (may turn relay off if no other rules match)
        reconcile_relay(relay_id, force=True)
    
    return JSONResponse({"ok": True})


@app.post("/api/rules/{rule_id}/toggle")
def api_rule_toggle(
    rule_id: str,
    request: Request,
    body: Dict[str, Any] = Body(...),
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
):
    """Toggle rule enabled state."""
    err = require_auth(request, x_api_key)
    if err:
        return err
    
    is_enabled = body.get("is_enabled")
    if not isinstance(is_enabled, bool):
        return JSONResponse({"ok": False, "error": "invalid_is_enabled"}, status_code=400)
    
    # Get relay_id before updating
    rule = db_get_relay_rule(rule_id)
    if not rule:
        return JSONResponse({"ok": False, "error": "not_found"}, status_code=404)
    
    relay_id = rule.get("relay_id")
    
    updated = db_update_relay_rule(rule_id, is_enabled=is_enabled)
    if not updated:
        return JSONResponse({"ok": False, "error": "update_failed"}, status_code=400)
    
    rule = db_get_relay_rule(rule_id)
    
    if relay_id:
        # Reconcile relay immediately when rule is enabled/disabled
        reconcile_relay(relay_id, force=True)
    
    return JSONResponse({"ok": True, "rule": rule})


@app.get("/api/relays/{relay_id}/events")
def api_relay_events(
    relay_id: str,
    request: Request,
    limit: int = 50,
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
):
    """Get relay events."""
    err = require_auth(request, x_api_key)
    if err:
        return err
    
    events = db_get_relay_events(relay_id, limit)
    return JSONResponse({"ok": True, "events": events})


# =========================
# API: Relay Control (Legacy/Header)
# =========================

@app.get("/api/relay/header")
def api_relay_header_get(request: Request, x_api_key: Optional[str] = Header(default=None, alias="X-API-Key")):
    """Legacy endpoint for header relay. Uses new system but returns old format."""
    err = require_auth(request, x_api_key)
    if err:
        return err
    
    relay = db_get_relay_device_by_name("heater")
    if relay:
        relay_id = relay["id"]
        state_data = db_get_relay_state_new(relay_id)
        if state_data:
            # Return state in inverted format for legacy compatibility
            # Backend stores actual hardware state, but UI expects inverted
            actual_state = state_data.get("actual_state") or state_data.get("state", "off")
            return JSONResponse({
                "ok": True,
                "name": HEADER_RELAY_NAME,
                "pin": HEADER_RELAY_PIN,
                "state": "off" if actual_state == "on" else "on",  # Inverted for legacy compatibility
            })
    
    # No fallback - relay_state_new is the single source of truth
    # If relay not found, return default
    return JSONResponse({
        "ok": True,
        "name": HEADER_RELAY_NAME,
        "pin": HEADER_RELAY_PIN,
        "state": "off",  # Default to off if relay not found
    })


@app.post("/api/relay/header")
def api_relay_header_post(
    request: Request,
    body: Dict[str, Any] = Body(...),
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
):
    err = require_auth(request, x_api_key)
    if err:
        return err
    
    # Extract and validate state from body
    state = body.get("state", "").strip().lower()
    if state not in ("on", "off"):
        return JSONResponse({"ok": False, "error": "invalid_state", "message": "state must be 'on' or 'off'"}, status_code=400)
    
    # Try new system first
    relay = db_get_relay_device_by_name("heater")
    if relay:
        relay_id = relay["id"]
        # Frontend sends inverted state (off when UI ON, on when UI OFF), so invert back
        actual_state = "off" if state == "on" else "on"
        
        if not _relay_lock.acquire(blocking=False):
            return JSONResponse({"ok": False, "error": "busy", "message": "Another relay operation in progress"}, status_code=429)
        
        try:
            # Execute hardware command using pinctrl
            result = apply_relay_hardware(relay_id, actual_state)
            if not result.get("ok"):
                _relay_lock.release()
                return JSONResponse({
                    "ok": False,
                    "error": result.get("error", "hardware_failed"),
                    "message": result.get("message", "Failed to apply hardware state"),
                }, status_code=500)
            
            # Update state using reconcile (manual mode)
            # Get old state for logging
            current_state_data = db_get_relay_state_new(relay_id)
            old_state = current_state_data.get("actual_state") or current_state_data.get("state", "off") if current_state_data else "off"
            
            # Use reconcile to set manual mode
            db_update_relay_state_new(
                relay_id=relay_id,
                mode="manual",
                manual_state=actual_state,
                manual_until=None
            )
            reconcile_relay(relay_id, force=True)
            
            _relay_lock.release()
            return JSONResponse({
                "ok": True,
                "name": HEADER_RELAY_NAME,
                "pin": HEADER_RELAY_PIN,
                "state": state,  # Return original state for legacy compatibility
            })
        except Exception as e:
            _relay_lock.release()
            return JSONResponse({
                "ok": False,
                "error": "exception",
                "message": str(e),
            }, status_code=500)
    
    # No fallback - use new system only
    # If we get here, the relay device wasn't found, which shouldn't happen after db_init()
    return JSONResponse({
        "ok": False,
        "error": "relay_not_found",
        "message": "Relay device not found in database",
    }, status_code=404)


# =========================
# Frontend routes
# =========================

def frontend_ready() -> bool:
    return (STATIC_DIR / "index.html").exists()


@app.get("/")
def root():
    if not frontend_ready():
        return JSONResponse({"error": "frontend_not_built"}, status_code=500)
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/dashboard")
def dashboard():
    if not frontend_ready():
        return JSONResponse({"error": "frontend_not_built"}, status_code=500)
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/{full_path:path}")
def spa_fallback(full_path: str):
    if not frontend_ready():
        return JSONResponse({"error": "frontend_not_built"}, status_code=500)
    target = STATIC_DIR / full_path
    if target.exists() and target.is_file():
        return FileResponse(target)
    return FileResponse(STATIC_DIR / "index.html")
