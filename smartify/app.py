import os
import time
import sqlite3
import threading
import subprocess
import uuid
import json
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


@app.on_event("startup")
def on_startup() -> None:
    db_init()
    # Step 1: Boot failsafe - immediately set all relays to OFF (before rules run)
    boot_failsafe_all_relays_off()
    # Step 2: Reconcile all relays from relay_state_new (single source of truth)
    # This will apply correct state based on AUTO+rules or MANUAL mode
    reconcile_all_relays_on_startup()
    # Start GPS reader thread
    t_gps = threading.Thread(target=_gps_reader_thread, daemon=True)
    t_gps.start()
    # Start DHT22 poller thread
    t_dht = threading.Thread(target=_dht22_poller_thread, daemon=True)
    t_dht.start()
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
    err = require_auth(request, x_api_key)
    if err:
        return err
    # Return cached values immediately (no blocking sensor reads)
    return JSONResponse(_temp_latest)


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

def _evaluate_temperature_condition(condition: Dict[str, Any], temp_data: Dict[str, Any]) -> bool:
    """Evaluate a temperature condition. Returns True if condition matches."""
    if condition.get("type") != "temperature":
        print(f"[Rule Engine] Condition type mismatch: {condition.get('type')} != 'temperature'")
        return False
    
    sensor_name = condition.get("sensor", "")
    operator = condition.get("operator", "")
    value = condition.get("value")
    
    if value is None:
        print(f"[Rule Engine] Condition value is None")
        return False
    
    # Map sensor names to indices: kombi=0, garaza=1
    sensor_map = {"kombi": 0, "garaza": 1}
    sensor_idx = sensor_map.get(sensor_name, -1)
    if sensor_idx < 0:
        print(f"[Rule Engine] Invalid sensor name: {sensor_name}")
        return False
    
    # Find sensor reading
    sensor_readings = temp_data.get("sensors", [])
    sensor_reading = None
    for sr in sensor_readings:
        if sr.get("sensor_index") == sensor_idx:
            sensor_reading = sr
            break
    
    if not sensor_reading:
        print(f"[Rule Engine] Sensor reading not found for {sensor_name} (index {sensor_idx})")
        return False
    
    if not sensor_reading.get("ok"):
        print(f"[Rule Engine] Sensor {sensor_name} is not OK: {sensor_reading.get('error')}")
        return False  # Sensor offline/invalid
    
    temp = sensor_reading.get("temperature_c")
    if temp is None:
        print(f"[Rule Engine] Temperature is None for sensor {sensor_name}")
        return False
    
    # Check if reading is stale (older than 60 seconds)
    ts = temp_data.get("ts")
    if ts:
        age = time.time() - ts
        if age > 60:
            print(f"[Rule Engine] Temperature data is stale: {age:.1f}s old")
            return False  # Stale data
    
    # Evaluate condition
    result = False
    if operator == "below":
        result = temp < value
        print(f"[Rule Engine] Evaluating: {temp}°C < {value}°C = {result}")
    elif operator == "above":
        result = temp > value
        print(f"[Rule Engine] Evaluating: {temp}°C > {value}°C = {result}")
    else:
        print(f"[Rule Engine] Unknown operator: {operator}")
        return False
    
    return result


def evaluate_rules(relay_id: str, temp_data: Dict[str, Any], current_state: Optional[str] = None) -> Tuple[Optional[str], Optional[Dict[str, Any]], bool]:
    """
    Deterministically evaluate enabled rules for a relay.
    Returns (desired_state, matched_rule, sensor_data_available) tuple.
    desired_state is "on" or "off" based on first matching rule, or None if sensor data unavailable.
    matched_rule is the rule dict that matched, or None if no rule matched.
    sensor_data_available is False if sensor data is unavailable (should preserve current state).
    
    Cooldown only prevents triggering a state CHANGE, not maintaining the current state.
    """
    rules = db_list_relay_rules(relay_id)
    enabled_rules = [r for r in rules if r.get("is_enabled", True)]
    
    if not enabled_rules:
        return ("off", None, True)  # No enabled rules -> default to off (sensor data not needed)
    
    # Check if we have valid sensor data
    sensors = temp_data.get("sensors", [])
    if not sensors:
        # No sensor data available - return None to preserve current state
        print(f"[Rule Engine] No sensor data available, preserving current state")
        return (None, None, False)
    
    # Check if any sensor readings are OK
    has_valid_data = any(s.get("ok", False) for s in sensors)
    if not has_valid_data:
        # No valid sensor data - return None to preserve current state
        print(f"[Rule Engine] No valid sensor data available, preserving current state")
        return (None, None, False)
    
    # Sort by priority (lower number = higher priority), then by creation time
    enabled_rules.sort(key=lambda x: (x.get("priority", 100), x.get("created_at", 0)))
    
    # Evaluate each rule in priority order
    now = int(time.time())
    for rule in enabled_rules:
        # Evaluate condition first
        condition = rule.get("condition", {})
        if not _evaluate_temperature_condition(condition, temp_data):
            continue  # Condition doesn't match, skip this rule
        
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
            return (rule_desired_state, rule, True)
        
        # Rule would change state - check cooldown
        last_triggered = rule.get("last_triggered_at")
        if last_triggered:
            age = now - last_triggered
            cooldown_sec = rule.get("cooldown_seconds", 60)
            if age < cooldown_sec:
                # Still in cooldown and would change state - skip this rule
                continue
        
        # Rule matches and either no cooldown or cooldown expired - first match wins
        return (rule_desired_state, rule, True)
    
    # No rule matched -> default to off (but only if we have valid sensor data)
    return ("off", None, True)


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
        # Auto mode: evaluate rules
        temp_data = _temp_latest.copy()
        # Pass current_actual to evaluate_rules so cooldown only applies to state changes
        desired_state_result, matched_rule, sensor_data_available = evaluate_rules(relay_id, temp_data, current_actual)
        
        if not sensor_data_available:
            # Sensor data unavailable - preserve current desired_state
            # Don't change desired_state, keep it as is
            print(f"[Reconcile] Sensor data unavailable, preserving current desired_state: {current_desired}")
            desired_state = current_desired  # Keep current desired_state
            source = "rule"
            reason = "Sensor data unavailable, preserving current state"
            matched_rule = None  # No rule matched due to sensor failure
        else:
            # Sensor data available - use the result
            desired_state = desired_state_result
            source = "rule"
            if matched_rule:
                # Build reason string
                condition = matched_rule.get("condition", {})
                sensor_name = condition.get("sensor", "")
                operator = condition.get("operator", "")
                value = condition.get("value")
                sensor_reading = None
                for sr in temp_data.get("sensors", []):
                    if sr.get("sensor_index") == (0 if sensor_name == "kombi" else 1):
                        sensor_reading = sr
                        break
                temp = sensor_reading.get("temperature_c") if sensor_reading else None
                reason = f"Rule '{matched_rule.get('name')}': {sensor_name.capitalize()} temp {operator} {value}°C (current: {temp:.1f}°C)"
                # Don't update last_triggered_at here - only update when hardware state actually changes
            else:
                reason = "No rule matched, default to off"
    
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
            result.append({
                "id": relay_id,
                "name": relay["name"],
                "pin": relay["pin"],
                "active_low": bool(relay.get("active_low", 0)),
                "state": state.get("actual_state") or state.get("state", "off") if state else "off",
                "mode": state.get("mode", "auto") if state else "auto",
                "manual_until": state.get("manual_until") if state else None,
                "updated_at": state.get("updated_at") if state else None,
                "is_enabled": bool(relay.get("is_enabled", True)),
            })
        
        return JSONResponse({"ok": True, "relays": result})
    except Exception as e:
        print(f"[API] Error listing relays: {e}")
        import traceback
        traceback.print_exc()
        return JSONResponse({"ok": False, "error": str(e), "relays": []}, status_code=500)


@app.get("/api/relays/{relay_id}")
def api_relay_get(relay_id: str, request: Request, x_api_key: Optional[str] = Header(default=None, alias="X-API-Key")):
    """Get relay details."""
    err = require_auth(request, x_api_key)
    if err:
        return err
    
    relay = db_get_relay_device(relay_id)
    if not relay:
        return JSONResponse({"ok": False, "error": "not_found"}, status_code=404)
    
    state = db_get_relay_state_new(relay_id)
    return JSONResponse({
        "ok": True,
        "relay": {
            "id": relay["id"],
            "name": relay["name"],
            "pin": relay["pin"],
            "active_low": bool(relay.get("active_low", 0)),
            "is_enabled": bool(relay.get("is_enabled", True)),
            "state": state.get("actual_state") or state.get("state", "off") if state else "off",
            "mode": state.get("mode", "auto") if state else "auto",
            "manual_until": state.get("manual_until") if state else None,
            "updated_at": state.get("updated_at") if state else None,
        },
    })


@app.post("/api/relays/{relay_id}/state")
def api_relay_set_state(
    relay_id: str,
    request: Request,
    body: Dict[str, Any] = Body(...),
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
):
    """Set relay state manually. Sets mode to 'manual' and uses reconcile to apply."""
    err = require_auth(request, x_api_key)
    if err:
        return err
    
    relay = db_get_relay_device(relay_id)
    if not relay:
        return JSONResponse({"ok": False, "error": "not_found"}, status_code=404)
    
    state = body.get("state", "").strip().lower()
    if state not in ("on", "off"):
        return JSONResponse({"ok": False, "error": "invalid_state"}, status_code=400)
    
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
        response_state = updated_state.get("actual_state") or updated_state.get("state", "off")
    else:
        response_state = state
    
    return JSONResponse({
        "ok": True,
        "state": response_state,
        "mode": mode,
        "manual_until": manual_until,
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
