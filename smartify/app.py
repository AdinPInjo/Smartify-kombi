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

# Import centralized logging
from smartify.logging_setup import logger, log_exception

# Import centralized configuration
from smartify.config import (
    DB_PATH,
    DATA_DIR,
    STATIC_DIR,
    SMARTIFY_USERNAME,
    SMARTIFY_PASSWORD,
    SMARTIFY_API_KEY,
    SMARTIFY_REQUIRE_AUTH,
    SMARTIFY_TRUST_LOCALHOST,
    SMARTIFY_SECRET,
    GPS_ENABLED,
    GPS_DEVICE,
    GPS_BAUD,
    DHT22_PINS,
    SENSOR_LOG_INTERVAL,
    HEADER_RELAY_NAME,
    HEADER_RELAY_PIN,
    _relay_lock,
    _rule_evaluator_thread,
)

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

# Import validators
from smartify.validators import validate_rule_action, validate_rule_condition

# Import database layer
from smartify.db import (
    db_init,
    db_connect,
    db_insert_temp,
    db_insert_sensor_sample,
    db_update_sensor_snapshot,
    db_upsert_sensor_snapshot,
    db_get_sensor_snapshot,
    db_insert_gps,
    db_query_temp_since,
    db_query_gps_since,
    db_get_relay_state,
    db_set_relay_state,
    db_get_relay_device_by_name,
    db_get_relay_device,
    db_list_relay_devices,
    db_create_relay_device,
    db_update_relay_device,
    db_get_relay_state_new,
    db_create_relay_state_new,
    db_set_relay_state_new,
    db_update_relay_state_new,
    db_list_relay_rules,
    db_get_relay_rule,
    db_create_relay_rule,
    db_update_relay_rule,
    db_delete_relay_rule,
    db_log_relay_event,
    db_get_relay_events,
    db_update_rule_last_triggered,
)

# Water level module
from smartify.water_level import api as water_level_api, service as water_level_service
from smartify.services import gps as gps_service
from smartify.services import weather as weather_service
from smartify.services import watchdog as watchdog_service
from smartify.services import db_integrity as db_integrity_service
from smartify import rule_engine

# Import core functions from extracted modules
# These are re-exported from app.py for backward compatibility
from smartify.auth import (
    is_localhost as _auth_is_localhost,
    is_authenticated as _auth_is_authenticated, 
    require_auth as _auth_require_auth,
    SMARTIFY_REQUIRE_AUTH as _SMARTIFY_REQUIRE_AUTH,
    SMARTIFY_API_KEY as _SMARTIFY_API_KEY,
    SMARTIFY_TRUST_LOCALHOST as _SMARTIFY_TRUST_LOCALHOST
)
from smartify.db import (
    db_list_relay_devices as _db_list_relay_devices,
    db_get_relay_state_new as _db_get_relay_state_new,
    db_list_relay_rules as _db_list_relay_rules,
    db_get_sensor_snapshot as _db_get_sensor_snapshot,
    db_query_temp_since as _db_query_temp_since,
    db_query_gps_since as _db_query_gps_since,
    _safe_dict_from_row as _db_safe_dict_from_row,
    DB_PATH as _DB_PATH_FROM_DB_MODULE
)
from smartify.utils import coerce_to_dict as _coerce_to_dict
from smartify.config import (
    SENSOR_WARMUP_SAMPLES as _SENSOR_WARMUP_SAMPLES,
    SENSOR_STALE_THRESHOLD as _SENSOR_STALE_THRESHOLD,
    DB_PATH as _DB_PATH_FROM_CONFIG,
    DATA_DIR as _DATA_DIR_FROM_CONFIG
)

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

_safe_dict_from_row = _db_safe_dict_from_row

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
        
        # Execute pinctrl command (ensure pin is configured as output)
        cmd = ["pinctrl", "set", str(pin), "op", physical_state]
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


# ===========================
# DB Functions moved to smartify/db.py
# ===========================
# All database interaction functions have been moved to smartify.db module.
# Import them at the top of this file.


# =========================
# Auth helpers
# =========================

def is_localhost(request: Request) -> bool:
    host = request.client.host if request.client else ""
    return host in ("127.0.0.1", "::1", "localhost")


def is_authenticated(request: Request, x_api_key: Optional[str]) -> bool:
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




# =========================
# Auth helpers
# =========================

# Re-export auth functions from smartify.auth module
is_localhost = _auth_is_localhost
is_authenticated = _auth_is_authenticated
require_auth = _auth_require_auth


# Initialize and include water level router (must be after require_auth is defined)
water_level_api.init_router(DB_PATH, require_auth, app.state)
app.include_router(water_level_api.router)

# Initialize and include health router
from smartify.api import health as health_api
health_router = health_api.create_health_router(
    is_authenticated_func=is_authenticated,
    require_auth_enabled=SMARTIFY_REQUIRE_AUTH,
    api_key_enabled=bool(SMARTIFY_API_KEY),
    trust_localhost_enabled=SMARTIFY_TRUST_LOCALHOST
)
app.include_router(health_router)

# Initialize and include relays router
from smartify.api import relays as relays_api
app.include_router(relays_api.router)

# Initialize and include sensors router
from smartify.api import sensors as sensors_api
app.include_router(sensors_api.router)

# Initialize and include gps router
from smartify.api import gps as gps_api
from smartify.api import weather as weather_api
from smartify.api import logs as logs_api
app.include_router(gps_api.router)
app.include_router(weather_api.router)
app.include_router(logs_api.router)

# Initialize and include network router
from smartify.api import network as network_api
app.include_router(network_api.router)

# Initialize and include ADS1115 router
from smartify.api import ads1115 as ads1115_api
app.include_router(ads1115_api.router)

# Initialize and include rules router
from smartify.api import rules as rules_api
app.include_router(rules_api.router)

# Initialize and include auth router
from smartify.api import auth as auth_api
app.include_router(auth_api.router)
# =========================
# Sensor: DHT22
# =========================

from smartify import state

_dht_lock = threading.Lock()

# Temperature snapshot system for stable readings
_sensor_samples: Dict[str, deque] = {}  # sensor_name -> deque of (temp, humidity, timestamp, ok)
_sensor_samples_lock = threading.Lock()
SENSOR_SAMPLE_INTERVAL = 5  # Sample every 5 seconds
SENSOR_SNAPSHOT_INTERVAL = 60  # Update snapshot every 60 seconds

# Re-export sensor constants from smartify.config
SENSOR_STALE_THRESHOLD = _SENSOR_STALE_THRESHOLD
SENSOR_WARMUP_SAMPLES = _SENSOR_WARMUP_SAMPLES

# Live sensor status (updated every 5s, used for warmup progress)
# Import from services.sensors module to share state
from smartify.services.sensors import SENSOR_LIVE_STATUS, _sensor_live_status_lock
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
    while True:
        try:
            state._thread_health["dht22_poller"] = {"last_heartbeat": int(time.time()), "status": "ok", "error": None}
            results = read_dht22_all()
            state._temp_latest.clear()
            state._temp_latest.update({
                "ts": int(time.time()),
                "sensors": results,
            })
        except Exception as e:
            state._thread_health["dht22_poller"] = {"last_heartbeat": int(time.time()), "status": "error", "error": str(e)}
            state._temp_latest.clear()
            state._temp_latest.update({
                "ts": int(time.time()),
                "sensors": [],
            })
            log_exception(logger, "[DHT22] Poller error", error=str(e))
        
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
            state._thread_health["sensor_sampler"] = {"last_heartbeat": now, "status": "ok", "error": None}
            
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
                    
                    # Persist sample to DB for audit trail and debugging
                    try:
                        db_insert_sensor_sample(sensor_name, temp, humidity, ok, now)
                    except Exception as e:
                        logger.error("[Sensor Sampler] Failed to persist sample for %s: %s", sensor_name, e)
                        import traceback
                        traceback.print_exc()
                    
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
            
            # Log sensor sample collection and persistence periodically (rate-limited: once per snapshot interval)
            if now % SENSOR_SNAPSHOT_INTERVAL < SENSOR_SAMPLE_INTERVAL:
                # Log individual sample readings
                persisted_ok = []
                for result in results:
                    sensor_idx = result.get("sensor_index", -1)
                    sensor_name = sensor_name_map.get(sensor_idx, f"sensor_{sensor_idx}")
                    temp = result.get("temperature_c")
                    humidity = result.get("humidity")
                    ok = result.get("ok", False)
                    print(f"[Sensor Sample] sensor={sensor_name} temp={temp} hum={humidity} ok={ok}")
                    if ok and temp is not None:
                        persisted_ok.append(sensor_name)
                
                # Log persistence success summary
                if persisted_ok:
                    sample_count_kombi = len(_sensor_samples.get("kombi", []))
                    sample_count_garaza = len(_sensor_samples.get("garaza", []))
                    logger.info("[Sensor Sampler] Persisted samples successfully - kombi: %d samples, garaza: %d samples", 
                               sample_count_kombi, sample_count_garaza)
            
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
                                print(f"[Sensor Snapshot] Updated {sensor_name}: {avg_temp:.1f}°C, {avg_humidity:.1f}% (from {sample_count} samples)")
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
            state._thread_health["sensor_sampler"] = {"last_heartbeat": int(time.time()), "status": "error", "error": str(e)}
            print(f"[Sensor Sampler] Error: {e}")
            log_exception(logger, "[Sensor Sampler] Thread error", error=str(e))
            time.sleep(SENSOR_SAMPLE_INTERVAL)


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
    def _start_dht_thread() -> None:
        t = threading.Thread(target=_dht22_poller_thread, daemon=True, name="DHT22Poller")
        t.start()

    def _start_sampler_thread() -> None:
        t = threading.Thread(target=_sensor_sampler_thread, daemon=True, name="SensorSampler")
        t.start()

    def _start_rule_thread() -> None:
        t = threading.Thread(target=_rule_evaluator_thread, daemon=True, name="RuleEvaluator")
        t.start()

    # Start GPS reader thread
    gps_service.start_gps_thread()
    # Start weather fetcher thread (background samples)
    weather_service.start_weather_thread()
    # Start DB integrity checker + backups
    db_integrity_service.start_db_integrity_thread()
    # Start DHT22 poller thread (for legacy API compatibility)
    _start_dht_thread()
    # Start sensor sampler thread (for snapshot system)
    _start_sampler_thread()
    # Start rule evaluator thread
    _start_rule_thread()
    # Start water level thread (using new module)
    water_level_service.start_water_level_thread(DB_PATH, app.state)

    # Watchdog registrations
    watchdog_service.register_thread("dht22_poller", _start_dht_thread, timeout_seconds=max(60, SENSOR_LOG_INTERVAL * 3))
    watchdog_service.register_thread("sensor_sampler", _start_sampler_thread, timeout_seconds=max(30, SENSOR_SAMPLE_INTERVAL * 6))
    watchdog_service.register_thread("gps", gps_service.start_gps_thread, timeout_seconds=90)
    watchdog_service.register_thread("weather", weather_service.start_weather_thread, timeout_seconds=3600)
    watchdog_service.register_thread("db_integrity", db_integrity_service.start_db_integrity_thread, timeout_seconds=3600 * 8)
    watchdog_service.register_thread("water_level", lambda: water_level_service.start_water_level_thread(DB_PATH, app.state), timeout_seconds=180)
    watchdog_service.start_watchdog_thread()


# Application state for sharing between modules
app_state: Dict[str, Any] = {}


# =========================
# API: ADS1115 ADC
# =========================
# Endpoints moved to smartify/api/ads1115.py


# =========================
# API: Temperature
# =========================

# Temperature endpoints moved to smartify/api/sensors.py


# =========================
# API: GPS
# =========================
# Endpoints moved to smartify/api/gps.py


# =========================
# Relay Automation Engine
# =========================

RULE_EVAL_INTERVAL = 5  # Evaluate rules every 5 seconds


def get_sensor_snapshot(sensor_name: str) -> Dict[str, Any]:
    """
    Get sensor snapshot with stale detection.
    Re-exports from smartify.services.sensors module.
    """
    from smartify.services.sensors import get_sensor_snapshot as _get_snapshot
    return _get_snapshot(sensor_name, db_get_sensor_snapshot, SENSOR_LIVE_STATUS, _sensor_live_status_lock)

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
    actual_state = current_actual  # Alias for evaluate_rules() call
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
        actual_state = current_actual
        desired_state_result, matched_rule, winner_info, sensor_ok, reason_str = evaluate_rules(relay_id, None, actual_state)
        desired_state = desired_state_result
        source = "auto"
        reason = reason_str or "Rule evaluation"

    # Normalize desired_state
    if desired_state not in ("on", "off"):
        desired_state = current_actual

    # Persist desired_state and mode (keeps API in sync)
    db_update_relay_state_new(relay_id, desired_state=desired_state, mode=mode)

    # No change needed
    if desired_state == current_actual:
        return False

    # Enforce min_on/min_off cooldowns unless forced
    min_on_seconds = int(device.get("min_on_seconds", 0) or 0)
    min_off_seconds = int(device.get("min_off_seconds", 0) or 0)
    if not force:
        if current_actual == "on" and desired_state == "off" and min_on_seconds > 0 and (now - last_applied) < min_on_seconds:
            return False
        if current_actual == "off" and desired_state == "on" and min_off_seconds > 0 and (now - last_applied) < min_off_seconds:
            return False

    # Apply hardware
    hw = apply_relay_hardware(relay_id, desired_state)
    if not hw.get("ok"):
        print(f"[Reconcile] Hardware apply failed for relay {relay_id}: {hw.get('message')}")
        return False

    # Update actual state and log event
    db_update_relay_state_new(relay_id, actual_state=desired_state, last_applied_at=now)
    rule_id = matched_rule.get("id") if isinstance(matched_rule, dict) else None
    db_log_relay_event(relay_id, source, current_actual, desired_state, reason, rule_id)
    if rule_id:
        db_update_rule_last_triggered(rule_id)

    return True

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
            # IMPORTANT: Only set pending=true for sensor issues if relay needs to change state.
            # If actual_state == desired_state, relay is already in correct state (pending=false).
            # Sensor staleness is reported via sensor_is_stale/age_seconds for visibility.
            if not sensor_ok and desired_state_result and actual_state and desired_state_result != actual_state:
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
                        pending_message = f"Cooldown: min_on ({min_on_seconds}s)"
                        cooldown_remaining = max(0, min_on_seconds - int(now - last_applied_at))
                    elif actual_state == "off" and desired_state_result == "on" and min_off_seconds > 0 and (now - last_applied_at) < min_off_seconds:
                        pending = True
                        pending_reason = "min_off"
                        pending_message = f"Cooldown: min_off ({min_off_seconds}s)"
                        cooldown_remaining = max(0, min_off_seconds - int(now - last_applied_at))
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
        if not bool(relay.get("is_enabled", True)):
            pending_info = {
                "pending": False,
                "pending_reason": "not_connected",
                "pending_message": "Not connected yet",
                "cooldown_remaining": None,
                "sensor_age_seconds": None,
                "sensor_sample_count": None,
                "sensor_is_ready": None,
                "sensor_is_stale": None,
                "source": "system",
            }
        
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


# =========================
# API: Relay Control (Legacy/Header)
# =========================

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

# Frontend endpoints moved to smartify/api/frontend.py

# Initialize and include frontend router (must be last to avoid catch-all shadowing API routes)
from smartify.api import frontend as frontend_api
app.include_router(frontend_api.router)
