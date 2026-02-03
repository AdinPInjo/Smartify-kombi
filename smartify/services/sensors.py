"""
Sensor reading business logic for Smartify.
"""
import time
import threading
from typing import Dict, Any, Optional

from smartify.config import SENSOR_WARMUP_SAMPLES, SENSOR_STALE_THRESHOLD

# Global state for sensor live status (updated by background threads in app.py)
# This is shared state that must be managed carefully
SENSOR_LIVE_STATUS: Dict[str, Dict[str, Any]] = {}
_sensor_live_status_lock = threading.Lock()


def get_sensor_snapshot(
    sensor_name: str,
    db_get_sensor_snapshot_func,
    live_status_dict: Optional[Dict[str, Dict[str, Any]]] = None,
    live_status_lock: Optional[threading.Lock] = None
) -> Dict[str, Any]:
    """
    Get sensor snapshot with stale detection.
    Uses live status for warmup progress (updates every 5s).
    Returns: value, updated_at, last_good_at, is_stale, age_seconds, is_ready
    ALWAYS returns age_seconds as int (never None) for safe integer operations.
    
    Args:
        sensor_name: Name of sensor to get snapshot for
        db_get_sensor_snapshot_func: Function to get snapshot from database
        live_status_dict: Optional live status dictionary (defaults to module global)
        live_status_lock: Optional lock for live status (defaults to module global)
    """
    # Use module globals if not provided (for backward compatibility)
    if live_status_dict is None:
        live_status_dict = SENSOR_LIVE_STATUS
    if live_status_lock is None:
        live_status_lock = _sensor_live_status_lock
    
    now = int(time.time())
    snapshot = db_get_sensor_snapshot_func(sensor_name)
    
    # Get live status (updated every 5s)
    with live_status_lock:
        live_status = live_status_dict.get(sensor_name, {})
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
