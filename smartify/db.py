"""
Database access functions for Smartify.
"""
import os
import json
import sqlite3
from pathlib import Path
from typing import Optional, Dict, Any, List

# Import DB_PATH from config (single source of truth)
from smartify.config import DB_PATH


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
    except Exception as e:
        print(f"[DB] CRITICAL: Unexpected error converting row at {context}: {e}, type={type(row).__name__}")
        return None


def db_list_relay_devices() -> List[Dict[str, Any]]:
    """List all relay devices."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT * FROM relay_devices ORDER BY name")
    rows = cur.fetchall()
    conn.close()
    return [_safe_dict_from_row(row, context="db_list_relay_devices") for row in rows if _safe_dict_from_row(row, context="db_list_relay_devices") is not None]


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


def db_list_relay_rules(relay_id: str) -> List[Dict[str, Any]]:
    """
    List rules for a relay. 
    Returns simplified rule dictionaries without validation.
    Full validation is done at rule evaluation time in app.py.
    """
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
                # If JSON parsing fails, set condition to empty dict
                print(f"[DB] Error parsing condition_json for rule {r.get('id', 'unknown')}: {e}")
                r["condition"] = {}
        else:
            r["condition"] = {}
        
        # Parse action (JSON or legacy string) - minimal parsing, no validation
        action_raw = r.get("action", "")
        if isinstance(action_raw, str) and action_raw.strip().startswith("{"):
            try:
                r["action"] = json.loads(action_raw)
            except (json.JSONDecodeError, TypeError, ValueError):
                r["action"] = action_raw
        else:
            r["action"] = action_raw
        
        # Convert SQLite integer boolean to Python boolean
        r["is_enabled"] = bool(r.get("is_enabled", 1))
        result.append(r)
    return result


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


def db_query_temp_since(since_ts: int, sensor_index: Optional[int] = None) -> List[Dict[str, Any]]:
    """Query temperature readings since a timestamp."""
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
    """Query GPS fixes since a timestamp."""
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
