import os
import time
import logging
import sqlite3
import threading
import subprocess
import uuid
import json
from collections import deque
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple

# =========================
# Configuration / Settings
# =========================
# All module-level constants defined here to prevent NameError on import.
# Override via environment variables as needed.

# Paths
REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = REPO_ROOT / "smartify" / "data" / "smartify.db"
DB_PATH = os.getenv("SMARTIFY_DB_PATH", str(DEFAULT_DB_PATH))
DATA_DIR = REPO_ROOT / "smartify" / "data"
STATIC_DIR = REPO_ROOT / "smartify-ui" / "dist"

# Authentication & Security
SMARTIFY_USERNAME = os.getenv("SMARTIFY_USERNAME", "admin")
SMARTIFY_PASSWORD = os.getenv("SMARTIFY_PASSWORD", "changeme")
SMARTIFY_API_KEY = os.getenv("SMARTIFY_API_KEY", "")
SMARTIFY_REQUIRE_AUTH = os.getenv("SMARTIFY_REQUIRE_AUTH", "1") in ("1", "true", "yes", "on")
SMARTIFY_TRUST_LOCALHOST = os.getenv("SMARTIFY_TRUST_LOCALHOST", "1") in ("1", "true", "yes", "on")
SMARTIFY_SECRET = os.getenv("SMARTIFY_SECRET", "change-this-secret-in-production")

# GPS configuration
GPS_ENABLED = os.getenv("GPS_ENABLED", "0") in ("1", "true", "yes", "on")
GPS_DEVICE = os.getenv("GPS_DEVICE", "/dev/serial0")
GPS_BAUD = int(os.getenv("GPS_BAUD", "9600"))

# DHT22 temperature/humidity sensor pins
DHT22_PINS_STR = os.getenv("DHT22_PINS", "")
if DHT22_PINS_STR.strip():
    DHT22_PINS = [int(p.strip()) for p in DHT22_PINS_STR.split(",") if p.strip().isdigit()]
else:
    DHT22_PINS = []  # No DHT22 sensors configured

# Sensor polling interval
SENSOR_LOG_INTERVAL = int(os.getenv("SENSOR_LOG_INTERVAL", "30"))

# Legacy header relay (single relay control)
HEADER_RELAY_NAME = os.getenv("HEADER_RELAY_NAME", "header")
HEADER_RELAY_PIN = int(os.getenv("HEADER_RELAY_PIN", "0"))

# Thread-safety lock for relay operations
_relay_lock = threading.Lock()

# Rule evaluator thread handle (set during startup)
_rule_evaluator_thread: Optional[threading.Thread] = None

# Startup log
print(f"[Config] DB_PATH={DB_PATH}")
print(f"[Config] GPS_ENABLED={GPS_ENABLED}, GPS_DEVICE={GPS_DEVICE if GPS_ENABLED else 'N/A'}")
print(f"[Config] DHT22_PINS={DHT22_PINS}")
print(f"[Config] SMARTIFY_REQUIRE_AUTH={SMARTIFY_REQUIRE_AUTH}")

from fastapi import FastAPI, Request, Form, Header, Body
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware

# FastAPI app must exist before any router init calls.
app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key=SMARTIFY_SECRET)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Water level module
from smartify.water_level import api as water_level_api, service as water_level_service
from smartify import rule_engine

# Startup sanity check: log ADS1115 module location
# This runs immediately on import, so it appears in service logs on startup
try:
    from smartify import ads1115
    print(f"[Startup] ADS1115 module loaded from: {ads1115.__file__}")
except ImportError as e:
    print(f"[Startup] WARNING: Could not import ads1115 module: {e}")
except Exception as e:
    print(f"[Startup] ERROR loading ads1115 module: {e}")


# =========================
# Helper Functions
# =========================

logger = logging.getLogger(__name__)

def coerce_to_dict(value: Any, *, context: str = "") -> dict:
    """
    Normalize user/db JSON-ish values into a dict safely.
    Accepts dict, JSON string, list/tuple of pairs, list of dicts.
    If value is list of strings or plain string that isn't JSON object, return {} and log warning.
    Never raises ValueError from dict(value).
    
    Args:
        value: The value to coerce to dict
        context: Context string for logging (e.g., "rule.params", "pending_state")
    
    Returns:
        dict: The coerced dictionary, or empty dict if coercion fails
    """
    # None -> empty dict
    if value is None:
        return {}
    
    # Already a dict -> return as-is
    if isinstance(value, dict):
        return value
    
    # String -> try JSON parse
    if isinstance(value, str):
        # Empty string -> empty dict
        if not value.strip():
            return {}
        
        try:
            parsed = json.loads(value)
            if isinstance(parsed, dict):
                return parsed
            else:
                # JSON parsed but not a dict (e.g., list, string, number)
                print(f"[coerce_to_dict] Invalid dict-like payload for {context}: "
                      f"JSON parsed to {type(parsed).__name__}, not dict (value={value[:100]}...)")
                return {}
        except (json.JSONDecodeError, TypeError, ValueError) as e:
            # Not valid JSON - could be a plain string like "heater" or "force"
            print(f"[coerce_to_dict] Invalid dict-like payload for {context}: "
                  f"got type=str value='{value[:100]}' (not valid JSON, dropping)")
            return {}
    
    # List or tuple -> try to convert
    if isinstance(value, (list, tuple)):
        # Empty list/tuple -> empty dict
        if not value:
            return {}
        
        # Check if all items are dicts -> merge them
        if all(isinstance(item, dict) for item in value):
            result = {}
            for item in value:
                result.update(item)
            return result
        
        # Check if all items are 2-element sequences (key-value pairs)
        # CRITICAL: Exclude strings! Strings have __len__ but dict(['force']) crashes
        # with "ValueError: dictionary update sequence element #0 has length 5; 2 is required"
        try:
            # Verify items are sequences (tuple/list) but NOT strings, and have exactly length 2
            if all(
                not isinstance(item, str) and 
                hasattr(item, '__len__') and 
                len(item) == 2 
                for item in value
            ):
                return dict(value)
        except (TypeError, ValueError) as e:
            # This should never happen now, but keep defensive catch
            print(f"[coerce_to_dict] Unexpected error converting list to dict for {context}: {e}")
            pass
        
        # List of non-dict, non-pairs (e.g., list of strings)
        sample = value[:3] if len(value) > 3 else value
        print(f"[coerce_to_dict] Invalid dict-like payload for {context}: "
              f"got type=list with non-dict items (sample={sample}, dropping)")
        return {}
    
    # Other types (int, float, bool, etc.) -> log warning and return empty dict
    print(f"[coerce_to_dict] Invalid dict-like payload for {context}: "
          f"got type={type(value).__name__} value={repr(value)[:100]} (dropping)")
    return {}


def safe_dict(value: Any, context: str) -> dict:
    """
    Safely coerce a value to dict without ever calling dict() on strings
    or list/tuple of strings. Returns {} on invalid inputs and logs details.
    """
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        logger.warning("[safe_dict] Rejecting string input for %s: %s", context, value[:200])
        return {}
    if isinstance(value, (list, tuple)):
        # Only allow iterable of 2-item tuples/lists (not strings)
        if all(isinstance(item, (list, tuple)) and len(item) == 2 and not isinstance(item, str) for item in value):
            try:
                return dict(value)
            except Exception as e:
                logger.error("[safe_dict] Failed to convert pairs for %s: %s", context, e)
                return {}
        sample = value[:10] if len(value) > 10 else value
        logger.warning(
            "[safe_dict] Rejecting list/tuple input for %s: sample=%s",
            context,
            [repr(x)[:50] for x in sample],
        )
        return {}
    logger.warning("[safe_dict] Rejecting unsupported type for %s: %s", context, type(value).__name__)
    return {}


def _debug_test_coerce_to_dict():
    """
    Manual test function for coerce_to_dict - NOT run on import.
    Tests that coerce_to_dict handles all malformed inputs safely without ValueError.
    
    Usage (in Python REPL or debugger):
        from smartify.app import _debug_test_coerce_to_dict
        _debug_test_coerce_to_dict()
    """
    print("\n=== Testing coerce_to_dict ===")
    
    test_cases = [
        ("force", "String length 5"),
        ("heater", "String length 6"),
        (["force"], "List with one string"),
        (["force", "heater"], "List with multiple strings"),
        ([("key", "val")], "List with one tuple pair"),
        ([("a", "b"), ("c", "d")], "List with multiple tuple pairs"),
        ({"valid": "dict"}, "Valid dict"),
        (None, "None"),
        (123, "Integer"),
        ([], "Empty list"),
        ('{"json": "string"}', "JSON string"),
        ("not json", "Non-JSON string"),
    ]
    
    passed = 0
    failed = 0
    
    for value, description in test_cases:
        try:
            result = coerce_to_dict(value, context=f"test:{description}")
            assert isinstance(result, dict), f"Result is not dict: {type(result)}"
            print(f"✓ PASS: {description} -> {result}")
            passed += 1
        except Exception as e:
            print(f"✗ FAIL: {description} -> Exception: {e}")
            failed += 1
    
    print(f"\n=== Results: {passed} passed, {failed} failed ===\n")
    return failed == 0


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


def _normalize_operator(operator: str) -> str:
    """Normalize comparison operator aliases to standard form."""
    operator_aliases = {
        "above": ">",
        "below": "<",
        "greater": ">",
        "less": "<",
        "eq": "==",
        "equals": "==",
        "gte": ">=",
        "lte": "<=",
        "gt": ">",
        "lt": "<",
    }
    return operator_aliases.get(str(operator).strip().lower(), str(operator).strip())


def apply_relay_hardware(relay_id: str, state: str) -> Dict[str, Any]:
    """
    Apply relay hardware command using pinctrl.
    Returns: {"ok": bool, "message": str}
    """
    try:
        # Get relay device info
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM relay_devices WHERE id = ?", (relay_id,))
        row = cur.fetchone()
        conn.close()
        
        if not row:
            return {"ok": False, "message": f"Relay {relay_id} not found"}
        
        device = dict(row)
        pin = device.get("pin")
        active_low = bool(device.get("active_low", False))
        
        if pin is None:
            return {"ok": False, "message": "Pin not configured"}
        
        return apply_relay_hardware_direct(pin, state, active_low)
    except Exception as e:
        return {"ok": False, "message": f"Hardware error: {e}"}


def apply_relay_hardware_direct(pin: int, state: str, active_low: bool = False) -> Dict[str, Any]:
    """
    Apply relay command directly to GPIO pin using pinctrl.
    Returns: {"ok": bool, "message": str}
    """
    try:
        # Determine physical pin state based on active_low
        if active_low:
            physical_state = "dl" if state == "on" else "dh"
        else:
            physical_state = "dh" if state == "on" else "dl"
        
        # Execute pinctrl command
        cmd = ["pinctrl", "set", str(pin), physical_state]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=2)
        
        if result.returncode == 0:
            return {"ok": True, "message": f"Pin {pin} set to {physical_state}"}
        else:
            return {"ok": False, "message": f"pinctrl failed: {result.stderr}"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "message": "pinctrl timeout"}
    except FileNotFoundError:
        return {"ok": False, "message": "pinctrl command not found"}
    except Exception as e:
        return {"ok": False, "message": f"Hardware error: {e}"}


def _normalize_condition_schema(condition: Any) -> Tuple[bool, Optional[str], Optional[Dict[str, Any]]]:
    """Normalize and validate composite/range condition schema."""
    if not isinstance(condition, dict):
        preview = repr(condition)[:120]
        return (False, f"condition must be a dict, got {type(condition).__name__}: {preview}", None)
    
    # Support both {op: "and"} and {"and": [...]} style
    if "op" in condition or "and" in condition or "or" in condition or "not" in condition:
        op = condition.get("op")
        if op is None:
            if "and" in condition:
                op = "and"
                condition = {"op": "and", "conditions": condition.get("and")}
            elif "or" in condition:
                op = "or"
                condition = {"op": "or", "conditions": condition.get("or")}
            elif "not" in condition:
                op = "not"
                condition = {"op": "not", "condition": condition.get("not")}
        op = str(op).lower().strip()
        if op in ("and", "or"):
            conditions = condition.get("conditions", [])
            if not isinstance(conditions, list):
                return (False, f"{op} conditions must be a list", None)
            normalized_list = []
            for sub in conditions:
                ok, err, normalized = _normalize_condition_schema(sub)
                if not ok:
                    return (False, err, None)
                normalized_list.append(normalized)
            return (True, None, {"op": op, "conditions": normalized_list})
        if op == "not":
            sub = condition.get("condition")
            ok, err, normalized = _normalize_condition_schema(sub)
            if not ok:
                return (False, err, None)
            return (True, None, {"op": "not", "condition": normalized})
        return (False, f"unknown op '{op}'", None)
    
    condition_type = condition.get("type")
    if not condition_type:
        return (False, "condition missing required field: type", None)
    
    if condition_type == "always":
        return (True, None, {"type": "always"})
    
    if condition_type in ("temperature", "humidity"):
        sensor = condition.get("sensor")
        if not sensor:
            return (False, f"{condition_type} condition missing required field: sensor", None)
        sensor = str(sensor)
        if sensor not in ("kombi", "garaza"):
            return (False, f"unknown sensor '{sensor}'", None)
        
        if "between" in condition and isinstance(condition.get("between"), dict):
            between = condition.get("between") or {}
            min_val = between.get("min")
            max_val = between.get("max")
            if not isinstance(min_val, (int, float)) or not isinstance(max_val, (int, float)):
                return (False, "between.min and between.max must be numbers", None)
            if min_val >= max_val:
                return (False, "between.min must be less than between.max", None)
            min_inclusive = bool(between.get("min_inclusive", True))
            max_inclusive = bool(between.get("max_inclusive", False))
            if condition_type == "humidity" and (min_val < 0 or max_val > 100):
                return (False, "humidity between range must be within 0..100", None)
            normalized = {
                "type": f"{condition_type}_between",
                "sensor": sensor,
                "min": float(min_val),
                "max": float(max_val),
                "min_inclusive": min_inclusive,
                "max_inclusive": max_inclusive,
            }
            return (True, None, normalized)
        
        cmp_raw = condition.get("cmp", condition.get("operator"))
        normalized_cmp = _normalize_operator(cmp_raw)
        if not normalized_cmp:
            return (False, f"invalid cmp/operator '{cmp_raw}', must be one of: <, >, <=, >= (or aliases: below, above)", None)
        
        value = condition.get("value")
        if not isinstance(value, (int, float)):
            return (False, f"value must be a number, got {type(value).__name__}", None)
        if condition_type == "humidity" and (value < 0 or value > 100):
            return (False, "humidity value must be within 0..100", None)
        
        normalized = {
            "type": condition_type,
            "sensor": sensor,
            "cmp": normalized_cmp,
            "value": float(value),
        }
        return (True, None, normalized)
    
    if condition_type in ("temperature_between", "humidity_between"):
        sensor = condition.get("sensor")
        if not sensor:
            return (False, f"{condition_type} missing required field: sensor", None)
        sensor = str(sensor)
        if sensor not in ("kombi", "garaza"):
            return (False, f"unknown sensor '{sensor}'", None)
        min_val = condition.get("min")
        max_val = condition.get("max")
        if not isinstance(min_val, (int, float)) or not isinstance(max_val, (int, float)):
            return (False, "min and max must be numbers", None)
        if min_val >= max_val:
            return (False, "min must be less than max", None)
        min_inclusive = bool(condition.get("min_inclusive", True))
        max_inclusive = bool(condition.get("max_inclusive", False))
        if condition_type == "humidity_between" and (min_val < 0 or max_val > 100):
            return (False, "humidity between range must be within 0..100", None)
        return (True, None, {
            "type": condition_type,
            "sensor": sensor,
            "min": float(min_val),
            "max": float(max_val),
            "min_inclusive": min_inclusive,
            "max_inclusive": max_inclusive,
        })
    
    return (False, f"unknown condition type '{condition_type}'", None)


def validate_rule_condition(condition: Any) -> Tuple[bool, Optional[str], Optional[Dict[str, Any]]]:
    """
    Validate a rule condition payload (composite + range aware).
    Returns: (is_valid, error_message, normalized_condition)
    """
    ok, err, normalized = _normalize_condition_schema(condition)
    if not ok:
        preview = repr(condition)[:120]
        print(f"[validate_rule_condition] invalid condition: {err} -> {preview}")
    return (ok, err, normalized)


def validate_rule_action(action: Any) -> Tuple[bool, Optional[str], Optional[Dict[str, Any]]]:
    """Validate and normalize rule action schema (set_state / temperature_band)."""
    if isinstance(action, str):
        action = action.strip()
        if action == "turn_on":
            return (True, None, {"type": "set_state", "state": "on"})
        if action == "turn_off":
            return (True, None, {"type": "set_state", "state": "off"})
        return (False, f"invalid action '{action}'", None)
    
    if not isinstance(action, dict):
        return (False, f"action must be a dict, got {type(action).__name__}", None)
    
    action_type = action.get("type")
    if action_type == "set_state":
        state = action.get("state")
        if state not in ("on", "off"):
            return (False, "set_state action requires state 'on' or 'off'", None)
        return (True, None, {"type": "set_state", "state": state})
    
    if action_type == "temperature_band":
        sensor = action.get("sensor")
        min_val = action.get("min", action.get("on_min"))
        max_val = action.get("max", action.get("off_max"))
        if not sensor:
            return (False, "temperature_band action missing required field: sensor", None)
        if not isinstance(min_val, (int, float)) or not isinstance(max_val, (int, float)):
            return (False, "temperature_band requires numeric min/max", None)
        min_inclusive = bool(action.get("min_inclusive", True))
        max_inclusive = bool(action.get("max_inclusive", False))
        on_state = action.get("on_state", "on")
        else_state = action.get("else_state", "off")
        if on_state not in ("on", "off") or else_state not in ("on", "off"):
            return (False, "temperature_band states must be 'on' or 'off'", None)
        normalized = {
            "type": "temperature_band",
            "sensor": str(sensor),
            "min": float(min_val),
            "max": float(max_val),
            "min_inclusive": min_inclusive,
            "max_inclusive": max_inclusive,
            "on_state": on_state,
            "else_state": else_state,
        }
        return (True, None, normalized)
    
    return (False, f"unknown action type '{action_type}'", None)


def _debug_test_rule_operators() -> bool:
    """Manual regression test for operator normalization/evaluation."""
    assert _normalize_operator(">") == ">"
    assert _normalize_operator("<") == "<"
    assert _normalize_operator(">=") == ">="
    assert _normalize_operator("<=") == "<="
    assert _normalize_operator("above") == ">"
    assert _normalize_operator("below") == "<"
    return True


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


def db_insert_temp(ts: int, sensor_index: int, t: Optional[float], h: Optional[float]) -> None:
    conn = sqlite3.connect(DB_PATH, timeout=5.0)
    cur = conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA busy_timeout=5000")
    cur.execute("PRAGMA synchronous=NORMAL")
    cur.execute(
        "INSERT INTO temperature_readings (ts, sensor_index, temperature_c, humidity) VALUES (?, ?, ?, ?)",
        (ts, sensor_index, t, h),
    )
    conn.commit()
    conn.close()


def db_insert_sensor_sample(sensor_name: str, temp: Optional[float], humidity: Optional[float], ok: bool, created_at: int) -> None:
    """Insert a raw sensor sample (optional, for debugging)."""
    conn = sqlite3.connect(DB_PATH, timeout=5.0)
    cur = conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA busy_timeout=5000")
    cur.execute("PRAGMA synchronous=NORMAL")
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
    """Update or insert sensor snapshot (canonical upsert implementation)."""
    conn = sqlite3.connect(DB_PATH, timeout=5.0)
    conn.row_factory = sqlite3.Row  # CRITICAL: set before any cursor/execute
    cur = conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA busy_timeout=5000")
    cur.execute("PRAGMA synchronous=NORMAL")

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
        conn.close()
        return

    conn.commit()
    conn.close()
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
    """Get sensor snapshot."""
    conn = sqlite3.connect(DB_PATH, timeout=5.0)
    conn.row_factory = sqlite3.Row  # CRITICAL: Set BEFORE creating cursor
    cur = conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA busy_timeout=5000")
    cur.execute("PRAGMA synchronous=NORMAL")
    cur.execute("SELECT * FROM sensor_snapshot WHERE sensor_name = ?", (sensor_name,))
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


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


def db_list_relay_rules(relay_id: str) -> List[Dict[str, Any]]:
    """List rules for a relay. Handles JSON parsing errors gracefully."""
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


# Initialize and include water level router (must be after require_auth is defined)
water_level_api.init_router(DB_PATH, require_auth, app.state)
app.include_router(water_level_api.router)


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

# Live sensor status (updated every 5s, used for warmup progress)
SENSOR_LIVE_STATUS: Dict[str, Dict[str, Any]] = {}  # sensor_name -> {valid_count_30s, last_valid_ts, last_attempt_ts, last_error, is_ready}
_sensor_live_status_lock = threading.Lock()
SENSOR_LIVE_STATUS_WINDOW = 30  # Count valid samples within last 30 seconds

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
    Also updates live sensor status for warmup progress tracking.
    """
    global _sensor_samples, SENSOR_LIVE_STATUS
    
    # Map sensor_index to sensor_name (kombi=0, garaza=1)
    sensor_name_map = {0: "kombi", 1: "garaza"}
    
    # Initialize deques and live status for each sensor
    with _sensor_samples_lock:
        for idx in range(len(DHT22_PINS)):
            sensor_name = sensor_name_map.get(idx, f"sensor_{idx}")
            if sensor_name not in _sensor_samples:
                _sensor_samples[sensor_name] = deque(maxlen=15)  # Keep last 15 samples (75s max)
    
    # Initialize live status tracking (deque of valid timestamps for 30s window)
    valid_timestamps: Dict[str, deque] = {}  # sensor_name -> deque of valid timestamps
    with _sensor_live_status_lock:
        for idx in range(len(DHT22_PINS)):
            sensor_name = sensor_name_map.get(idx, f"sensor_{idx}")
            valid_timestamps[sensor_name] = deque(maxlen=10)  # Max 10 timestamps (50s)
            SENSOR_LIVE_STATUS[sensor_name] = {
                "valid_count_30s": 0,
                "last_valid_ts": None,
                "last_attempt_ts": None,
                "last_error": None,
                "is_ready": False
            }
    
    last_snapshot_time = int(time.time())
    last_snapshot_time = (last_snapshot_time // SENSOR_SNAPSHOT_INTERVAL) * SENSOR_SNAPSHOT_INTERVAL  # Align to minute boundary
    
    while True:
        try:
            now = int(time.time())
            
            # Read all sensors
            results = read_dht22_all()
            
            # Store samples in memory and update live status
            with _sensor_samples_lock:
                for result in results:
                    sensor_idx = result.get("sensor_index", -1)
                    sensor_name = sensor_name_map.get(sensor_idx)
                    if not sensor_name:
                        continue
                    
                    temp = result.get("temperature_c")
                    humidity = result.get("humidity")
                    ok = result.get("ok", False)
                    error = result.get("error")
                    
                    # Store sample (temp, humidity, timestamp, ok)
                    if sensor_name not in _sensor_samples:
                        _sensor_samples[sensor_name] = deque(maxlen=15)
                    _sensor_samples[sensor_name].append((temp, humidity, now, ok))
                    
                    # Update live status (every 5s)
                    with _sensor_live_status_lock:
                        # Update last_attempt_ts always
                        SENSOR_LIVE_STATUS[sensor_name]["last_attempt_ts"] = now
                        
                        if ok and temp is not None and humidity is not None:
                            # Valid reading: add timestamp to deque
                            valid_ts_deque = valid_timestamps.get(sensor_name)
                            if valid_ts_deque is None:
                                valid_ts_deque = deque(maxlen=10)
                                valid_timestamps[sensor_name] = valid_ts_deque
                            valid_ts_deque.append(now)
                            
                            # Count valid samples within last 30 seconds
                            cutoff = now - SENSOR_LIVE_STATUS_WINDOW
                            valid_count_30s = sum(1 for ts in valid_ts_deque if ts >= cutoff)
                            
                            # Update live status
                            SENSOR_LIVE_STATUS[sensor_name]["valid_count_30s"] = valid_count_30s
                            SENSOR_LIVE_STATUS[sensor_name]["last_valid_ts"] = now
                            SENSOR_LIVE_STATUS[sensor_name]["last_error"] = None
                            SENSOR_LIVE_STATUS[sensor_name]["is_ready"] = valid_count_30s >= SENSOR_WARMUP_SAMPLES
                        else:
                            # Invalid reading: update error but don't overwrite last_valid_ts
                            SENSOR_LIVE_STATUS[sensor_name]["last_error"] = error or "Invalid reading"
                            # Recalculate valid_count_30s from existing timestamps
                            valid_ts_deque = valid_timestamps.get(sensor_name)
                            if valid_ts_deque:
                                cutoff = now - SENSOR_LIVE_STATUS_WINDOW
                                valid_count_30s = sum(1 for ts in valid_ts_deque if ts >= cutoff)
                                SENSOR_LIVE_STATUS[sensor_name]["valid_count_30s"] = valid_count_30s
                                SENSOR_LIVE_STATUS[sensor_name]["is_ready"] = valid_count_30s >= SENSOR_WARMUP_SAMPLES
                    
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
                            
                            # Update snapshot (defensive: never let this crash sampler thread)
                            try:
                                db_update_sensor_snapshot(
                                    sensor_name=sensor_name,
                                    avg_temp=avg_temp,
                                    avg_humidity=avg_humidity,
                                    sample_count=sample_count,
                                    window_start=window_start,
                                    window_end=window_end,
                                    last_good_at=last_good_at,
                                    updated_at=now,
                                )
                                print(f"[Sensor Snapshot] Updated {sensor_name}: {avg_temp:.1f}°C (from {sample_count} samples)")
                            except Exception as e:
                                logger.error("[Sensor Sampler] Snapshot update failed for %s: %s", sensor_name, e)
                                import traceback
                                traceback.print_exc()
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
    # Start water level thread (using new module)
    water_level_service.start_water_level_thread(DB_PATH, app.state)


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


# Application state for sharing between modules
app_state: Dict[str, Any] = {}


# =========================
# API: ADS1115 ADC
# =========================

@app.get("/api/ads1115/read")
def api_ads1115_read(
    request: Request,
    channel: int = 0,
    bus: int = 1,
    addr: int = 0x48,
    pga: float = 4.096,
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
):
    """
    Read voltage from ADS1115 ADC channel.
    
    Args:
        channel: Channel number (0-3)
        bus: I2C bus number (default 1)
        addr: I2C address (default 0x48)
        pga: PGA voltage range (default 4.096V)
    
    Returns:
        JSON with ok, voltage, raw_value, channel, or error/reason
    """
    err = require_auth(request, x_api_key)
    if err:
        return err
    
    # Validate channel
    if channel not in (0, 1, 2, 3):
        return JSONResponse({
            "ok": False,
            "error": "invalid_channel",
            "reason": "Channel must be 0-3",
            "channel": channel
        }, status_code=400)
    
    try:
        # Import ads1115 module (same directory)
        import ads1115
        ads_detect = ads1115.ads_detect
        ads_read_voltage = ads1115.ads_read_voltage
        ads_read_raw_single_ended = ads1115.ads_read_raw_single_ended
    except ImportError as e:
        import traceback
        error_detail = traceback.format_exc()
        print(f"[API] Error importing ads1115: {e}\n{error_detail}")
        return JSONResponse({
            "ok": False,
            "error": "module_error",
            "reason": f"Failed to import ads1115 module: {e}",
            "channel": channel
        })
    except AttributeError as e:
        import traceback
        error_detail = traceback.format_exc()
        print(f"[API] Error: ads1115 module missing required functions: {e}\n{error_detail}")
        return JSONResponse({
            "ok": False,
            "error": "module_error",
            "reason": f"ads1115 module missing required functions: {e}",
            "channel": channel
        })
    
    # Detect ADS1115
    if not ads_detect(bus=bus, addr=addr):
        return JSONResponse({
            "ok": False,
            "error": "ads_not_found",
            "reason": f"ADS1115 not found at address 0x{addr:02X} on bus {bus}",
            "channel": channel,
            "bus": bus,
            "addr": f"0x{addr:02X}"
        })
    
    # Read voltage
    voltage = ads_read_voltage(channel, bus=bus, addr=addr, pga=pga, sps=128, retries=3)
    raw_value = ads_read_raw_single_ended(channel, bus=bus, addr=addr, pga=pga, sps=128, retries=3)
    
    if voltage is None or raw_value is None:
        return JSONResponse({
            "ok": False,
            "error": "read_failed",
            "reason": "Failed to read from ADS1115 channel (I/O error or timeout)",
            "channel": channel,
            "bus": bus,
            "addr": f"0x{addr:02X}"
        })
    
    return JSONResponse({
        "ok": True,
        "channel": channel,
        "voltage": voltage,
        "raw_value": raw_value,
        "pga": pga,
        "bus": bus,
        "addr": f"0x{addr:02X}"
    })


@app.get("/api/ads1115/detect")
def api_ads1115_detect(
    request: Request,
    bus: int = 1,
    addr: int = 0x48,
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
):
    """
    Detect if ADS1115 is present on I2C bus.
    
    Returns:
        JSON with ok, detected, bus, addr
    """
    err = require_auth(request, x_api_key)
    if err:
        return err
    
    try:
        # Import ads1115 module (same directory)
        import ads1115
        ads_detect = ads1115.ads_detect
    except ImportError as e:
        import traceback
        error_detail = traceback.format_exc()
        print(f"[API] Error importing ads1115: {e}\n{error_detail}")
        return JSONResponse({
            "ok": False,
            "error": "module_error",
            "reason": f"Failed to import ads1115 module: {e}",
            "detected": False,
            "bus": bus,
            "addr": f"0x{addr:02X}"
        })
    except AttributeError as e:
        import traceback
        error_detail = traceback.format_exc()
        print(f"[API] Error: ads1115 module missing required functions: {e}\n{error_detail}")
        return JSONResponse({
            "ok": False,
            "error": "module_error",
            "reason": f"ads1115 module missing required functions: {e}",
            "detected": False,
            "bus": bus,
            "addr": f"0x{addr:02X}"
        })
    
    detected = ads_detect(bus=bus, addr=addr)
    
    return JSONResponse({
        "ok": True,
        "detected": detected,
        "bus": bus,
        "addr": f"0x{addr:02X}"
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


@app.get("/api/sensors/latest")
def api_sensors_latest(request: Request, x_api_key: Optional[str] = Header(default=None, alias="X-API-Key")):
    """Return latest snapshot for all sensors (temp + humidity)."""
    err = require_auth(request, x_api_key)
    if err:
        return err
    
    kombi_snapshot = get_sensor_snapshot("kombi")
    garaza_snapshot = get_sensor_snapshot("garaza")
    return JSONResponse({
        "ts": int(time.time()),
        "kombi": {
            "temp_c": kombi_snapshot.get("avg_temp"),
            "humidity_percent": kombi_snapshot.get("avg_humidity"),
            "sample_count": kombi_snapshot.get("sample_count"),
            "updated_at": kombi_snapshot.get("updated_at"),
            "last_good_at": kombi_snapshot.get("last_good_at"),
            "age_seconds": kombi_snapshot.get("age_seconds"),
            "is_stale": kombi_snapshot.get("is_stale"),
            "is_ready": kombi_snapshot.get("is_ready"),
        },
        "garaza": {
            "temp_c": garaza_snapshot.get("avg_temp"),
            "humidity_percent": garaza_snapshot.get("avg_humidity"),
            "sample_count": garaza_snapshot.get("sample_count"),
            "updated_at": garaza_snapshot.get("updated_at"),
            "last_good_at": garaza_snapshot.get("last_good_at"),
            "age_seconds": garaza_snapshot.get("age_seconds"),
            "is_stale": garaza_snapshot.get("is_stale"),
            "is_ready": garaza_snapshot.get("is_ready"),
        },
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
    Uses live status for warmup progress (updates every 5s).
    Returns: value, updated_at, last_good_at, is_stale, age_seconds, is_ready
    ALWAYS returns age_seconds as int (never None) for safe integer operations.
    """
    now = int(time.time())
    snapshot = db_get_sensor_snapshot(sensor_name)
    
    # Get live status (updated every 5s)
    with _sensor_live_status_lock:
        live_status = SENSOR_LIVE_STATUS.get(sensor_name, {})
        live_valid_count = live_status.get("valid_count_30s", 0)
        live_is_ready = live_status.get("is_ready", False)
        live_last_valid_ts = live_status.get("last_valid_ts")
        live_last_attempt_ts = live_status.get("last_attempt_ts", 0)
    
    if not snapshot:
        # No snapshot yet - use live status for warmup progress
        # Age is time since last attempt (or 0 if never attempted)
        age_seconds = max(0, now - live_last_attempt_ts) if live_last_attempt_ts > 0 else 0
        is_stale = age_seconds > SENSOR_STALE_THRESHOLD
        
        return {
            "sensor_name": sensor_name,
            "avg_temp": None,
            "avg_humidity": None,
            "sample_count": live_valid_count,  # Use live count for warmup progress
            "updated_at": None,
            "last_good_at": live_last_valid_ts,
            "is_stale": is_stale,
            "age_seconds": age_seconds,  # Always int, never None
            "is_ready": live_is_ready,  # Use live is_ready
        }
    
    # Snapshot exists - use it for temperature values, but use live status for warmup if not ready
    last_good_at = snapshot.get("last_good_at") or 0
    updated_at = snapshot.get("updated_at") or 0
    snapshot_sample_count = snapshot.get("sample_count") or 0
    
    # Always compute age_seconds as int (never None)
    # Use last_good_at if available, otherwise updated_at, otherwise 0
    reference_time = last_good_at if last_good_at else (updated_at if updated_at else 0)
    age_seconds = max(0, now - reference_time) if reference_time > 0 else 0
    
    # Stale if no valid samples for 10 minutes
    is_stale = age_seconds > SENSOR_STALE_THRESHOLD
    
    # If snapshot is not ready yet, use live status for warmup progress
    # Otherwise use snapshot sample_count
    if snapshot_sample_count < SENSOR_WARMUP_SAMPLES:
        # Snapshot not ready - use live status
        sample_count = live_valid_count
        is_ready = live_is_ready
    else:
        # Snapshot is ready - use snapshot values
        sample_count = snapshot_sample_count
        is_ready = True
    
    return {
        "sensor_name": sensor_name,
        "avg_temp": snapshot.get("avg_temp"),
        "avg_humidity": snapshot.get("avg_humidity"),
        "sample_count": sample_count,  # Live count during warmup, snapshot count when ready
        "updated_at": updated_at if updated_at else None,
        "last_good_at": last_good_at if last_good_at else None,
        "is_stale": is_stale,
        "age_seconds": age_seconds,  # Always int, never None
        "is_ready": is_ready,
    }

def _evaluate_temperature_condition(condition: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
    """
    Evaluate a temperature condition using snapshot data.
    Returns: (result: bool, reason: Optional[str])
    If sensor is stale or not ready, returns (False, reason) to force OFF.
    
    Defensive checks:
    - Checks is_ready FIRST (before any age_seconds math)
    - Safely handles None/missing fields
    - Always coerces age_seconds to int
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
    
    # Defensive check: ensure snapshot has required fields
    if not snapshot:
        return (False, "sensor_no_snapshot")
    
    # Check if sensor is not ready (warmup period) - CHECK THIS FIRST before age calculations
    is_ready = snapshot.get("is_ready", False)
    if not is_ready:
        sample_count = snapshot.get("sample_count", 0)
        return (False, f"sensor_warming_up({sample_count}/{SENSOR_WARMUP_SAMPLES} samples)")
    
    # Check if sensor is stale (no valid samples for 10 minutes)
    # Now safe to use age_seconds since is_ready was checked first
    is_stale = snapshot.get("is_stale", False)
    if is_stale:
        # Safely coerce age_seconds to int (should never be None from get_sensor_snapshot, but defensive)
        age_seconds = snapshot.get("age_seconds")
        if age_seconds is None:
            age_seconds = 0
        age_seconds = int(age_seconds)
        age_min = age_seconds // 60
        return (False, f"sensor_stale(>{age_min}m)")
    
    # Get temperature from snapshot
    temp = snapshot.get("avg_temp")
    if temp is None:
        return (False, f"sensor_no_data")
    
    # Normalize operator (supports below/above and symbols)
    normalized_operator = _normalize_operator(operator)
    if not normalized_operator:
        return (False, f"Invalid operator: {operator}")

    # Evaluate condition
    if normalized_operator == "<":
        result = temp < value
    elif normalized_operator == ">":
        result = temp > value
    elif normalized_operator == "<=":
        result = temp <= value
    elif normalized_operator == ">=":
        result = temp >= value
    else:
        return (False, f"Invalid operator: {operator}")
    
    print(f"[Rule Engine] Evaluating snapshot {sensor_name}: {temp:.1f}°C {normalized_operator} {value}°C = {result}")
    return (result, None)


def _evaluate_condition(condition: Dict[str, Any]) -> Tuple[bool, Optional[str], str, Dict[str, Any]]:
    """Delegates to rule_engine (pure logic)."""
    return rule_engine._evaluate_condition(condition, get_sensor_snapshot)

def evaluate_single_rule(rule: Dict[str, Any], relay_id: str) -> Dict[str, Any]:
    """Delegates to rule_engine (pure logic)."""
    return rule_engine.evaluate_single_rule(rule, get_sensor_snapshot)

def evaluate_rules(relay_id: str, temp_data: Optional[Dict[str, Any]] = None, current_state: Optional[str] = None) -> Tuple[Optional[str], Optional[Dict[str, Any]], Optional[Dict[str, Any]], bool, Optional[str]]:
    """Delegates to rule_engine (pure logic)."""
    rules = db_list_relay_rules(relay_id)
    return rule_engine.evaluate_rules(rules, get_sensor_snapshot, current_state)

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
    
    # Initialize all variables that may be used later (prevent UnboundLocalError)
    desired_state = None
    matched_rule = None
    source = "unknown"
    reason = "Unknown"
    
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
        matched_rule = None  # No rule in manual mode
    else:
        # Auto mode: evaluate rules using snapshot (not raw temp_data)
        # Auto mode: evaluate rules using snapshot (not raw temp_data)
        # Pass current_actual to evaluate_rules so cooldown only applies to state changes
        desired_state_result, matched_rule, winner_info, sensor_ok, reason_str = evaluate_rules(relay_id, None, actual_state)
        if winner_info and isinstance(winner_info, dict):
            snapshot_meta = (winner_info.get("snapshot") or {}).get("snapshot_meta", {})
            if isinstance(snapshot_meta, dict) and len(snapshot_meta) == 1:
                meta = next(iter(snapshot_meta.values()))
                if isinstance(meta, dict):
                    sensor_age_seconds = meta.get("age_seconds")
def _get_relay_pending_state(relay_id: str) -> Dict[str, Any]:
    """
    Determine if relay is in a pending/transitional state (cooldown, reconciling, startup, sensor issues).
    Returns dict with pending status, human-readable message, and detailed sensor/cooldown info.
    NEVER throws - always returns safe defaults on error.
    """
    now = int(time.time())
    pending = False
    pending_reason: Optional[str] = None
    pending_message: Optional[str] = None
    cooldown_remaining: Optional[int] = None
    sensor_age_seconds: Optional[int] = None
    sensor_sample_count: Optional[int] = None
    sensor_is_ready: Optional[bool] = None
    sensor_is_stale: Optional[bool] = None
    source: Optional[str] = None
    mode: str = "auto"
    try:
        relay_state = db_get_relay_state_new(relay_id)
        if not relay_state:
            return {
                "pending": True,
                "pending_reason": "startup",
                "pending_message": "System starting… initializing sensors",
                "cooldown_remaining": None,
                "sensor_age_seconds": None,
                "sensor_sample_count": None,
                "sensor_is_ready": None,
                "sensor_is_stale": None,
                "source": "startup"
            }
        actual_state = relay_state.get("actual_state")
        desired_state = relay_state.get("desired_state")
        last_applied_at = relay_state.get("last_applied_at", 0)
        mode = relay_state.get("mode", "auto")
        device = db_get_relay_device(relay_id)
        if device and not bool(device.get("is_enabled", True)):
            return {
                "pending": False,
                "pending_reason": None,
                "pending_message": None,
                "cooldown_remaining": None,
                "sensor_age_seconds": None,
                "sensor_sample_count": None,
                "sensor_is_ready": None,
                "sensor_is_stale": None,
                "source": "disabled"
            }
        if actual_state is None or actual_state == "":
            pending = True
            pending_reason = "reconciling"
            pending_message = "Applying relay state… please wait"
            source = "startup" if last_applied_at == 0 else "rule"
        elif desired_state and desired_state != actual_state:
            pending = True
            pending_reason = "reconciling"
            pending_message = "Applying relay state… please wait"
            source = mode
        if mode == "auto" and not pending:
            desired_state_result, matched_rule, winner_info, sensor_ok, reason_str = evaluate_rules(relay_id, None, actual_state)
            if winner_info and isinstance(winner_info, dict):
                snapshot_meta = (winner_info.get("snapshot") or {}).get("snapshot_meta", {})
                if isinstance(snapshot_meta, dict) and len(snapshot_meta) == 1:
                    meta = next(iter(snapshot_meta.values()))
                    if isinstance(meta, dict):
                        sensor_age_seconds = meta.get("age_seconds")
                        sensor_sample_count = meta.get("sample_count")
                        sensor_is_ready = meta.get("is_ready")
                        sensor_is_stale = meta.get("is_stale")
            if not sensor_ok:
                pending = True
                pending_reason = "sensor_unavailable"
                pending_message = f"Sensor unavailable: {reason_str} (holding last state)"
                source = "sensor"
            else:
                if desired_state_result and actual_state and desired_state_result != actual_state:
                    min_on_seconds = int(device.get("min_on_seconds", 0) or 0) if device else 0
                    min_off_seconds = int(device.get("min_off_seconds", 0) or 0) if device else 0
                    if actual_state == "on" and desired_state_result == "off" and min_on_seconds > 0 and (now - last_applied_at) < min_on_seconds:
                        pending = True
                        pending_reason = "min_on"
                        cooldown_remaining = min_on_seconds - (now - last_applied_at)
                        pending_message = f"Min ON time active: {cooldown_remaining}s remaining"
                        source = "rule"
                    elif actual_state == "off" and desired_state_result == "on" and min_off_seconds > 0 and (now - last_applied_at) < min_off_seconds:
                        pending = True
                        pending_reason = "min_off"
                        cooldown_remaining = min_off_seconds - (now - last_applied_at)
                        pending_message = f"Min OFF time active: {cooldown_remaining}s remaining"
                        source = "rule"
                    elif matched_rule is not None:
                        try:
                            runtime_status = evaluate_single_rule(matched_rule, relay_id)
                            if runtime_status.get("reason_code") == "cooldown":
                                pending = True
                                pending_reason = "cooldown"
                                cooldown_remaining = runtime_status.get("cooldown_remaining")
                                pending_message = f"Cooldown active: {cooldown_remaining}s remaining"
                                source = "rule"
                        except Exception:
                            pass
                if not pending and desired_state_result and actual_state and desired_state_result != actual_state:
                    pending = True
                    pending_reason = "reconciling"
                    pending_message = "Applying relay state… please wait"
                    source = "rule"
        final_source = source if source is not None else mode
        return {
            "pending": pending,
            "pending_reason": pending_reason,
            "pending_message": pending_message or (f"Relay is in {pending_reason} state" if pending_reason else None),
            "cooldown_remaining": cooldown_remaining,
            "sensor_age_seconds": sensor_age_seconds,
            "sensor_sample_count": sensor_sample_count,
            "sensor_is_ready": sensor_is_ready,
            "sensor_is_stale": sensor_is_stale,
            "source": final_source
        }
    except Exception as e:
        print(f"[_get_relay_pending_state] Error for relay {relay_id}: {e}")
        import traceback
        traceback.print_exc()
        return {
            "pending": False,
            "pending_reason": "unknown_error",
            "pending_message": f"Pending state error: {str(e)}",
            "cooldown_remaining": None,
            "sensor_age_seconds": None,
            "sensor_sample_count": None,
            "sensor_is_ready": None,
            "sensor_is_stale": None,
            "source": "unknown"
        }

def _public_relay_mode(relay_state: Optional[Dict[str, Any]]) -> str:
    """Map internal mode/manual_state to public mode (off/on/auto)."""
    if not relay_state:
        return "auto"
    mode = relay_state.get("mode", "auto")
    if mode == "auto":
        return "auto"
    manual_state = relay_state.get("manual_state") or relay_state.get("desired_state") or relay_state.get("state")
    return manual_state if manual_state in ("on", "off") else "off"


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
            
            # Get pending state info for each relay
            pending_info = _get_relay_pending_state(relay_id)
            
            result.append({
                "id": relay_id,
                "name": relay["name"],
                "pin": relay["pin"],
                "active_low": bool(relay.get("active_low", 0)),
                "state": hardware_state,
                "mode": _public_relay_mode(state),
                "desired_state": state.get("desired_state") if state else None,
                "manual_until": state.get("manual_until") if state else None,
                "updated_at": state.get("updated_at") if state else None,
                "is_enabled": bool(relay.get("is_enabled", True)),
                "min_on_seconds": relay.get("min_on_seconds", 0),
                "min_off_seconds": relay.get("min_off_seconds", 0),
                "pending": pending_info["pending"],
                "pending_reason": pending_info["pending_reason"],
                "pending_message": pending_info["pending_message"],
                "cooldown_remaining": pending_info["cooldown_remaining"],
                "sensor_age_seconds": pending_info["sensor_age_seconds"],
                "sensor_sample_count": pending_info["sensor_sample_count"],
                "sensor_is_ready": pending_info["sensor_is_ready"],
                "sensor_is_stale": pending_info["sensor_is_stale"],
                "source": pending_info["source"]
            })
        
        return JSONResponse({"ok": True, "relays": result})
    except Exception as e:
        # NEVER return 500 - always return valid JSON with safe fallback
        print(f"[API] Error listing relays: {e}")
        import traceback
        traceback.print_exc()
        return JSONResponse({"ok": True, "relays": [], "error": "Failed to list relays"})


@app.post("/api/relays")
def api_relay_create(
    request: Request,
    body: Dict[str, Any] = Body(...),
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
):
    """Create a new relay device and initialize state."""
    err = require_auth(request, x_api_key)
    if err:
        return err
    
    name = str(body.get("name", "")).strip()
    pin = body.get("pin")
    if not name:
        return JSONResponse({"ok": False, "error": "name_required"}, status_code=400)
    if not isinstance(pin, int):
        return JSONResponse({"ok": False, "error": "pin_required", "message": "pin must be integer"}, status_code=400)
    
    existing = db_get_relay_device_by_name(name)
    if existing:
        return JSONResponse({"ok": False, "error": "name_exists", "message": "Relay name already exists"}, status_code=400)
    
    active_low = bool(body.get("active_low", False))
    is_enabled = bool(body.get("is_enabled", True))
    min_on_seconds = int(body.get("min_on_seconds", 0) or 0)
    min_off_seconds = int(body.get("min_off_seconds", 0) or 0)
    
    relay_id = db_create_relay_device(
        name=name,
        pin=pin,
        active_low=active_low,
        is_enabled=is_enabled,
        min_on_seconds=min_on_seconds,
        min_off_seconds=min_off_seconds,
    )
    db_create_relay_state_new(relay_id=relay_id, state="off", mode="auto")
    relay = db_get_relay_device(relay_id)
    return JSONResponse({"ok": True, "relay": relay}, status_code=201)


@app.patch("/api/relays/{relay_id}")
def api_relay_update(
    relay_id: str,
    request: Request,
    body: Dict[str, Any] = Body(...),
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
):
    """Update relay device fields (rename/config)."""
    err = require_auth(request, x_api_key)
    if err:
        return err
    
    relay = db_get_relay_device(relay_id)
    if not relay:
        return JSONResponse({"ok": False, "error": "not_found"}, status_code=404)
    
    name = body.get("name")
    if name is not None:
        name = str(name).strip()
        if not name:
            return JSONResponse({"ok": False, "error": "name_required"}, status_code=400)
        existing = db_get_relay_device_by_name(name)
        if existing and existing.get("id") != relay_id:
            return JSONResponse({"ok": False, "error": "name_exists"}, status_code=400)
    
    pin = body.get("pin")
    active_low = body.get("active_low")
    is_enabled = body.get("is_enabled")
    min_on_seconds = body.get("min_on_seconds")
    min_off_seconds = body.get("min_off_seconds")
    
    updated = db_update_relay_device(
        relay_id=relay_id,
        name=name,
        pin=pin,
        active_low=active_low,
        is_enabled=is_enabled,
        min_on_seconds=min_on_seconds,
        min_off_seconds=min_off_seconds,
    )
    if not updated:
        return JSONResponse({"ok": False, "error": "update_failed"}, status_code=400)
    relay = db_get_relay_device(relay_id)
    return JSONResponse({"ok": True, "relay": relay})


@app.post("/api/relays/{relay_id}/mode")
def api_relay_set_mode(
    relay_id: str,
    request: Request,
    body: Dict[str, Any] = Body(...),
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
):
    """Set relay mode: off | on | auto."""
    err = require_auth(request, x_api_key)
    if err:
        return err
    
    relay = db_get_relay_device(relay_id)
    if not relay:
        return JSONResponse({"ok": False, "error": "not_found"}, status_code=404)
    
    mode = str(body.get("mode", "")).strip().lower()
    if mode not in ("off", "on", "auto"):
        return JSONResponse({"ok": False, "error": "invalid_mode"}, status_code=400)
    
    if mode == "auto":
        db_update_relay_state_new(relay_id=relay_id, mode="auto", manual_state=None, desired_state=None)
    else:
        db_update_relay_state_new(relay_id=relay_id, mode="manual", manual_state=mode, desired_state=mode)
    reconcile_relay(relay_id, force=True)
    return JSONResponse({"ok": True, "mode": mode})


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
                "mode": _public_relay_mode(state),
                "desired_state": state.get("desired_state") if state else None,
                "manual_until": state.get("manual_until") if state else None,
                "updated_at": state.get("updated_at") if state else None,
                "min_on_seconds": relay.get("min_on_seconds", 0),
                "min_off_seconds": relay.get("min_off_seconds", 0),
                "pending": pending_info["pending"],
                "pending_reason": pending_info["pending_reason"],
                "pending_message": pending_info["pending_message"],
                "cooldown_remaining": pending_info["cooldown_remaining"],
                "sensor_age_seconds": pending_info["sensor_age_seconds"],
                "sensor_sample_count": pending_info["sensor_sample_count"],
                "sensor_is_ready": pending_info["sensor_is_ready"],
                "sensor_is_stale": pending_info["sensor_is_stale"],
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
                "pending_reason": "error",
                "pending_message": "Error retrieving relay state",
                "cooldown_remaining": None,
                "sensor_age_seconds": None,
                "sensor_sample_count": None,
                "sensor_is_ready": None,
                "sensor_is_stale": None,
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
    
    # Validate relay_id - reject undefined/null/invalid
    if not relay_id or relay_id in ("undefined", "null", "None") or not relay_id.strip():
        return JSONResponse({
            "ok": False,
            "error": "invalid_relay_id",
            "message": "Invalid relay ID",
            "state": "off",
            "pending": False
        }, status_code=400)
    
    try:
        # Check if relay is in pending state (cooldown/reconciling)
        pending_info = _get_relay_pending_state(relay_id)
        if pending_info["pending"]:
            # Return error response but with HTTP 200 (never 500)
            # Use the human-readable message from pending_info
            error_msg = pending_info["pending_message"] or f"Relay is in {pending_info['pending_reason']} state"
            
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
                "pending_reason": pending_info["pending_reason"],
                "pending_message": pending_info["pending_message"],
                "cooldown_remaining": pending_info["cooldown_remaining"],
                "sensor_age_seconds": pending_info["sensor_age_seconds"],
                "sensor_sample_count": pending_info["sensor_sample_count"],
                "sensor_is_ready": pending_info["sensor_is_ready"],
                "sensor_is_stale": pending_info["sensor_is_stale"],
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
        
        # Apply hardware command directly (manual override)
        result = apply_relay_hardware(relay_id, state)
        
        # Check if hardware apply succeeded
        if not result.get("ok"):
            # Hardware apply failed - return error
            error_msg = result.get("message", result.get("error", "Failed to apply hardware"))
            return JSONResponse({
                "ok": False,
                "error": "hardware_failed",
                "message": error_msg,
                "state": state,
                "pending": False
            })
        
        # Hardware apply succeeded - update actual_state in DB
        now_time = int(time.time())
        db_update_relay_state_new(
            relay_id,
            actual_state=state,
            desired_state=state,  # In manual mode, desired == actual
            last_applied_at=now_time
        )
        
        # Log event
        db_log_relay_event(
            relay_id,
            "manual",
            "unknown",  # Previous state unknown
            state,
            "Manual override",
            None
        )
        
        # Best effort: try to reconcile (but don't fail if it errors)
        try:
            reconcile_relay(relay_id, force=True)
        except Exception as reconcile_error:
            # Hardware was already successfully applied, so log warning but don't fail
            print(f"[API] Warning: Hardware applied successfully but reconcile failed: {reconcile_error}")
            import traceback
            traceback.print_exc()
        
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
            "pending_reason": updated_pending["pending_reason"],
            "pending_message": updated_pending["pending_message"],
            "cooldown_remaining": updated_pending["cooldown_remaining"],
            "sensor_age_seconds": updated_pending["sensor_age_seconds"],
            "sensor_sample_count": updated_pending["sensor_sample_count"],
            "sensor_is_ready": updated_pending["sensor_is_ready"],
            "sensor_is_stale": updated_pending["sensor_is_stale"],
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
            "pending_reason": "error",
            "pending_message": "Error setting relay state",
            "cooldown_remaining": None,
            "sensor_age_seconds": None,
            "sensor_sample_count": None,
            "sensor_is_ready": None,
            "sensor_is_stale": None,
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
    """
    List rules for a relay with runtime status.
    ALWAYS returns 200 OK with JSON, never 500.
    Each rule is wrapped in try/except so one bad rule doesn't break the list.
    """
    err = require_auth(request, x_api_key)
    if err:
        return err
    
    try:
        rules = db_list_relay_rules(relay_id)
        relay_state = db_get_relay_state_new(relay_id)
        current_actual = relay_state.get("actual_state") if relay_state else None
        try:
            _, winner_rule, _winner_info, _sensor_ok, _reason = evaluate_rules(relay_id, None, current_actual)
            winner_id = winner_rule.get("id") if isinstance(winner_rule, dict) else None
        except Exception:
            winner_id = None
        
        # Add runtime status for each rule
        rules_with_status = []
        for rule in rules:
            try:
                # Safely coerce rule to dict (in case it's a string or invalid type)
                if not isinstance(rule, dict):
                    rule = coerce_to_dict(rule, context="api_relay_rules_list.rule")
                    if not rule:
                        # Skip invalid rules
                        print(f"[API] Skipping invalid rule (not a dict): {type(rule).__name__}")
                        continue
                
                # Ensure rule has required fields with defaults
                rule_dict = {
                    "id": rule.get("id", "unknown"),
                    "relay_id": rule.get("relay_id", relay_id),
                    "name": rule.get("name", "Unnamed Rule"),
                    "condition": rule.get("condition", {}),
                    "action": rule.get("action", {"type": "set_state", "state": "off"}),
                    "priority": rule.get("priority", 100),
                    "cooldown_seconds": rule.get("cooldown_seconds", 60),
                    "is_enabled": rule.get("is_enabled", False),
                    "last_triggered_at": rule.get("last_triggered_at"),
                    "created_at": rule.get("created_at"),
                    "updated_at": rule.get("updated_at")
                }
                ok_condition, _err, normalized_condition = validate_rule_condition(rule_dict["condition"])
                if ok_condition and normalized_condition is not None:
                    rule_dict["condition"] = normalized_condition
                
                # Safely evaluate runtime status (wrapped in try/except)
                try:
                    runtime_status = evaluate_single_rule(rule_dict, relay_id)
                except Exception as eval_error:
                    # If evaluate_single_rule itself crashes, return safe error status
                    print(f"[API] evaluate_single_rule crashed for rule {rule_dict.get('id')}: {eval_error}")
                    import traceback
                    traceback.print_exc()
                    runtime_status = {
                        "can_evaluate": False,
                        "matched": False,
                        "reason_code": "error",
                        "message": f"Evaluation error: {str(eval_error)[:200]}",
                        "sensor_name": None,
                        "snapshot_temp": None,
                        "threshold": None,
                        "operator": None,
                        "age_seconds": 0,
                        "sample_count": 0,
                        "cooldown_remaining": 0
                    }
                
                # Attach runtime status to rule
                runtime_status["is_winner"] = bool(winner_id and rule_dict["id"] == winner_id)
                rule_dict["runtime_status"] = runtime_status
                rules_with_status.append(rule_dict)
                
            except Exception as e:
                # If processing one rule fails completely, include it with error status
                rule_id = rule.get('id', 'unknown') if isinstance(rule, dict) else 'unknown'
                rule_name = rule.get('name', 'Unknown') if isinstance(rule, dict) else 'Unknown'
                print(f"[API] Error processing rule {rule_id}: {e}")
                import traceback
                traceback.print_exc()
                
                # Create minimal safe rule representation
                rule_dict = {
                    "id": rule_id,
                    "relay_id": relay_id,
                    "name": rule_name,
                    "condition": {},
                    "action": {"type": "set_state", "state": "off"},
                    "priority": 100,
                    "cooldown_seconds": 60,
                    "is_enabled": False,
                    "runtime_status": {
                        "can_evaluate": False,
                        "matched": False,
                        "reason_code": "error",
                        "message": f"Processing error: {str(e)[:200]}",
                        "sensor_name": None,
                        "snapshot_temp": None,
                        "threshold": None,
                        "operator": None,
                        "age_seconds": 0,
                        "sample_count": 0,
                        "cooldown_remaining": 0
                    }
                }
                rules_with_status.append(rule_dict)
        
        # ALWAYS return 200 OK with rules list (even if all failed)
        return JSONResponse({"ok": True, "rules": rules_with_status}, status_code=200)
        
    except Exception as e:
        # Outer exception handler - if db_list_relay_rules itself fails
        print(f"[API] Fatal error in /api/relays/{relay_id}/rules: {e}")
        import traceback
        traceback.print_exc()
        # Still return 200 OK (dashboard expects ok:true/false, not HTTP 500)
        return JSONResponse({
            "ok": False,
            "error": "internal_error",
            "message": f"Failed to load rules: {str(e)[:200]}",
            "rules": []
        }, status_code=200)


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
    
    # Validate condition (composite/range schema)
    condition_raw = body.get("condition", {})
    is_valid, error_msg, condition = validate_rule_condition(condition_raw)
    if not is_valid or condition is None:
        return JSONResponse({
            "ok": False,
            "error": "invalid_condition",
            "message": error_msg,
            "received_type": type(condition_raw).__name__
        }, status_code=400)
    
    action_raw = body.get("action")
    is_valid_action, action_error, action = validate_rule_action(action_raw)
    if not is_valid_action or action is None:
        return JSONResponse({
            "ok": False,
            "error": "invalid_action",
            "message": action_error or "Invalid action payload"
        }, status_code=400)
    
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


@app.post("/api/relays/{relay_id}/rules/temperature-band")
def api_relay_rule_create_temperature_band(
    relay_id: str,
    request: Request,
    body: Dict[str, Any] = Body(...),
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
):
    """Create a temperature band rule (range-based thermostat)."""
    err = require_auth(request, x_api_key)
    if err:
        return err
    
    relay = db_get_relay_device(relay_id)
    if not relay:
        return JSONResponse({"ok": False, "error": "not_found"}, status_code=404)
    
    name = body.get("name", "").strip()
    if not name:
        return JSONResponse({"ok": False, "error": "name_required"}, status_code=400)
    
    condition_raw = {
        "type": "temperature_between",
        "sensor": body.get("sensor"),
        "min": body.get("min"),
        "max": body.get("max"),
        "min_inclusive": body.get("min_inclusive", True),
        "max_inclusive": body.get("max_inclusive", False),
    }
    is_valid_condition, condition_error, condition = validate_rule_condition(condition_raw)
    if not is_valid_condition or condition is None:
        return JSONResponse({
            "ok": False,
            "error": "invalid_condition",
            "message": condition_error or "Invalid temperature band payload"
        }, status_code=400)
    
    action_raw = {"type": "set_state", "state": body.get("on_state", "on")}
    is_valid_action, action_error, action = validate_rule_action(action_raw)
    if not is_valid_action or action is None:
        return JSONResponse({
            "ok": False,
            "error": "invalid_action",
            "message": action_error or "Invalid action payload"
        }, status_code=400)
    
    priority = int(body.get("priority", 100))
    cooldown_seconds = int(body.get("cooldown_seconds", 60))
    is_enabled = body.get("is_enabled", True)
    if cooldown_seconds < 5:
        cooldown_seconds = 5
    
    rule_id = db_create_relay_rule(relay_id, name, condition, action, priority, cooldown_seconds, is_enabled)
    rule = db_get_relay_rule(rule_id)
    
    reconcile_relay(relay_id, force=True)
    return JSONResponse({"ok": True, "rule": rule}, status_code=201)


@app.post("/api/relays/{relay_id}/rules/humidity-band")
def api_relay_rule_create_humidity_band(
    relay_id: str,
    request: Request,
    body: Dict[str, Any] = Body(...),
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
):
    """Create a humidity band rule (range-based)."""
    err = require_auth(request, x_api_key)
    if err:
        return err
    
    relay = db_get_relay_device(relay_id)
    if not relay:
        return JSONResponse({"ok": False, "error": "not_found"}, status_code=404)
    
    name = body.get("name", "").strip()
    if not name:
        return JSONResponse({"ok": False, "error": "name_required"}, status_code=400)
    
    condition_raw = {
        "type": "humidity_between",
        "sensor": body.get("sensor"),
        "min": body.get("min"),
        "max": body.get("max"),
        "min_inclusive": body.get("min_inclusive", True),
        "max_inclusive": body.get("max_inclusive", False),
    }
    is_valid_condition, condition_error, condition = validate_rule_condition(condition_raw)
    if not is_valid_condition or condition is None:
        return JSONResponse({
            "ok": False,
            "error": "invalid_condition",
            "message": condition_error or "Invalid humidity band payload"
        }, status_code=400)
    
    action_raw = {"type": "set_state", "state": body.get("on_state", "on")}
    is_valid_action, action_error, action = validate_rule_action(action_raw)
    if not is_valid_action or action is None:
        return JSONResponse({
            "ok": False,
            "error": "invalid_action",
            "message": action_error or "Invalid action payload"
        }, status_code=400)
    
    priority = int(body.get("priority", 100))
    cooldown_seconds = int(body.get("cooldown_seconds", 60))
    is_enabled = body.get("is_enabled", True)
    if cooldown_seconds < 5:
        cooldown_seconds = 5
    
    rule_id = db_create_relay_rule(relay_id, name, condition, action, priority, cooldown_seconds, is_enabled)
    rule = db_get_relay_rule(rule_id)
    
    reconcile_relay(relay_id, force=True)
    return JSONResponse({"ok": True, "rule": rule}, status_code=201)


@app.put("/api/rules/{rule_id}")
def api_rule_update(
    rule_id: str,
    request: Request,
    body: Dict[str, Any] = Body(...),
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
):
    """
    Update a rule from dashboard UI.
    Accepts: name, condition, action, priority, cooldown_seconds, is_enabled (or enabled).
    NEVER returns 500 - returns 400 for validation errors, 200 for success.
    """
    err = require_auth(request, x_api_key)
    if err:
        return err
    
    try:
        rule = db_get_relay_rule(rule_id)
        if not rule:
            return JSONResponse({"ok": False, "error": "not_found", "message": "Rule not found"}, status_code=404)
        
        # Extract fields from body (support both is_enabled and enabled for UI compatibility)
        name = body.get("name")
        condition_raw = body.get("condition")
        action = body.get("action")
        priority = body.get("priority")
        cooldown_seconds = body.get("cooldown_seconds")
        is_enabled = body.get("is_enabled")
        if is_enabled is None:
            is_enabled = body.get("enabled")  # UI might send "enabled" instead
        
        # Validate condition if provided (composite/range schema)
        condition = None
        if condition_raw is not None:
            is_valid, error_msg, condition = validate_rule_condition(condition_raw)
            if not is_valid or condition is None:
                return JSONResponse({
                    "ok": False,
                    "error": "invalid_condition",
                    "message": error_msg,
                    "received_type": type(condition_raw).__name__
                }, status_code=400)
        
        # Validate action if provided
        if action is not None:
            is_valid_action, action_error, action = validate_rule_action(action)
            if not is_valid_action or action is None:
                return JSONResponse({
                    "ok": False,
                    "error": "invalid_action",
                    "message": action_error or "Invalid action payload"
                }, status_code=400)
        
        # Enforce minimum cooldown
        if cooldown_seconds is not None and cooldown_seconds < 5:
            cooldown_seconds = 5
        
        # Update rule in database
        updated = db_update_relay_rule(rule_id, name, condition, action, priority, cooldown_seconds, is_enabled)
        if not updated:
            return JSONResponse({
                "ok": False,
                "error": "update_failed",
                "message": "Failed to update rule in database"
            }, status_code=400)
        
        # Get updated rule (safely)
        try:
            rule = db_get_relay_rule(rule_id)
            relay_id = rule.get("relay_id") if rule else None
        except Exception as e:
            print(f"[API] Error fetching updated rule {rule_id}: {e}")
            relay_id = None
            rule = {"id": rule_id, "error": "fetch_failed"}
        
        # Reconcile relay to apply updated rule immediately (in background, don't block response)
        if relay_id:
            try:
                reconcile_relay(relay_id, force=True)
            except Exception as e:
                # Don't fail the API response if reconciliation fails
                print(f"[API] Error reconciling relay {relay_id} after rule update: {e}")
        
        # Return success with updated rule
        return JSONResponse({"ok": True, "rule": rule}, status_code=200)
        
    except Exception as e:
        # Catch-all for unexpected errors - return 400 (not 500)
        print(f"[API] Unexpected error in PUT /api/rules/{rule_id}: {e}")
        import traceback
        traceback.print_exc()
        return JSONResponse({
            "ok": False,
            "error": "internal_error",
            "message": f"Failed to update rule: {str(e)[:200]}"
        }, status_code=400)


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
    """
    Toggle rule enabled state.
    ALWAYS returns 200 OK with JSON response.
    Does NOT compute runtime_status (to avoid evaluation errors blocking toggle).
    """
    err = require_auth(request, x_api_key)
    if err:
        return err
    
    try:
        # Get is_enabled from body (support both is_enabled and enabled for UI compatibility)
        is_enabled = body.get("is_enabled")
        if is_enabled is None:
            is_enabled = body.get("enabled")
        
        if not isinstance(is_enabled, bool):
            return JSONResponse({
                "ok": False,
                "error": "invalid_is_enabled",
                "message": "is_enabled must be a boolean (true/false)"
            }, status_code=400)
        
        # Get rule to check it exists and get relay_id
        rule = db_get_relay_rule(rule_id)
        if not rule:
            return JSONResponse({
                "ok": False,
                "error": "not_found",
                "message": "Rule not found"
            }, status_code=404)
        
        relay_id = rule.get("relay_id")
        
        # Update rule enabled state in database
        updated = db_update_relay_rule(rule_id, is_enabled=is_enabled)
        if not updated:
            return JSONResponse({
                "ok": False,
                "error": "update_failed",
                "message": "Failed to update rule in database"
            }, status_code=400)
        
        # Reconcile relay immediately when rule is enabled/disabled (in background, don't block)
        if relay_id:
            try:
                reconcile_relay(relay_id, force=True)
            except Exception as e:
                # Don't fail the API response if reconciliation fails
                print(f"[API] Error reconciling relay {relay_id} after toggle: {e}")
        
        # Return simple success response (no runtime_status to avoid evaluation errors)
        return JSONResponse({
            "ok": True,
            "rule_id": rule_id,
            "is_enabled": is_enabled
        }, status_code=200)
        
    except Exception as e:
        # Catch-all for unexpected errors - return 400 (not 500)
        print(f"[API] Unexpected error in POST /api/rules/{rule_id}/toggle: {e}")
        import traceback
        traceback.print_exc()
        return JSONResponse({
            "ok": False,
            "error": "internal_error",
            "message": f"Failed to toggle rule: {str(e)[:200]}"
        }, status_code=400)


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

# Mount static assets if they exist
if (STATIC_DIR / "assets").exists():
    app.mount("/assets", StaticFiles(directory=str(STATIC_DIR / "assets")), name="assets")

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
