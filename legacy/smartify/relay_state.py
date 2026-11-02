"""
Relay state and pending state helpers for Smartify.

This module contains logic for determining relay pending states
(cooldown, reconciling, sensor issues, etc).
"""
import time
from typing import Dict, Any, Optional

# Import from dedicated modules (no app.py dependency)
from smartify.db import db_get_relay_state_new, db_list_relay_rules, db_get_sensor_snapshot
from smartify.utils import coerce_to_dict
from smartify.config import SENSOR_WARMUP_SAMPLES
from smartify.services.sensors import get_sensor_snapshot


def _get_relay_pending_state(relay_id: str) -> Dict[str, Any]:
    """
    Determine if relay is in a pending/transitional state (cooldown, reconciling, startup, sensor issues).
    Returns dict with pending status, human-readable message, and detailed sensor/cooldown info.
    NEVER throws - always returns safe defaults on error.
    
    All dependencies imported from dedicated modules - NO app.py dependency.
    """
    # Initialize all variables at top to prevent UnboundLocalError
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
    mode: str = "auto"  # Default mode
    
    try:
        # Get relay state - using imported function
        relay_state = db_get_relay_state_new(relay_id)
        if not relay_state:
            # State not found - could be during startup
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
        mode = relay_state.get("mode", "auto")  # Update mode from state
        
        # Check if actual_state is unknown (startup/reconciling)
        if actual_state is None or actual_state == "":
            pending = True
            pending_reason = "reconciling"
            pending_message = "Applying relay state… please wait"
            source = "startup" if last_applied_at == 0 else "rule"
        
        # Check if desired_state differs from actual_state (reconciling)
        elif desired_state and desired_state != actual_state:
            pending = True
            pending_reason = "reconciling"
            pending_message = "Applying relay state… please wait"
            source = mode  # "manual" or "rule"
        
        # Check sensor status for AUTO mode relays (if rules depend on sensors)
        if mode == "auto" and not pending:
            rules = db_list_relay_rules(relay_id)
            
            # Normalize rules input - ensure it's always a list
            if rules is None:
                rules = []
            elif isinstance(rules, str):
                # Rules should never be a string, but handle gracefully
                print(f"[_get_relay_pending_state] WARNING: rules is string, not list (value={rules[:50]}...)")
                rules = []
            elif isinstance(rules, dict):
                # Rules should never be a dict, but handle gracefully
                print(f"[_get_relay_pending_state] WARNING: rules is dict, not list")
                rules = [rules]  # Wrap in list
            elif not isinstance(rules, (list, tuple)):
                print(f"[_get_relay_pending_state] WARNING: rules is {type(rules).__name__}, not list")
                rules = []
            
            # Safely filter enabled rules - coerce each to dict first
            enabled_rules = []
            for r in rules:
                if not isinstance(r, dict):
                    r = coerce_to_dict(r, context="_get_relay_pending_state.filter_rules")
                    if not r:
                        continue  # Skip invalid rules
                if r.get("is_enabled", True):
                    enabled_rules.append(r)
            
            # Check if any rule depends on a sensor that is stale or warming up
            for rule in enabled_rules:
                # rule is already validated above, but double-check for safety
                if not isinstance(rule, dict):
                    print(f"[_get_relay_pending_state] Skipping invalid rule type={type(rule).__name__}")
                    continue
                
                # Wrap per-rule evaluation to prevent one bad rule from crashing
                try:
                    condition = rule.get("condition", {})
                    # Safety: Ensure condition is a dict
                    if not isinstance(condition, dict):
                        condition = coerce_to_dict(condition, context="_get_relay_pending_state.condition")
                    
                    if condition.get("type") == "temperature":
                        sensor_name = condition.get("sensor", "")
                        if sensor_name:
                            snapshot = get_sensor_snapshot(sensor_name, db_get_sensor_snapshot)
                            if not snapshot:
                                continue  # Skip if snapshot missing
                            
                            # Extract sensor info for response
                            sensor_age_seconds = snapshot.get("age_seconds", 0)
                            sensor_sample_count = snapshot.get("sample_count", 0)
                            sensor_is_ready = snapshot.get("is_ready", False)
                            sensor_is_stale = snapshot.get("is_stale", False)
                            
                            # Check is_ready first (before age calculations)
                            if not sensor_is_ready:
                                pending = True
                                pending_reason = "sensor_warming_up"
                                pending_message = f"Waiting for temperature snapshot… collected {sensor_sample_count}/{SENSOR_WARMUP_SAMPLES} samples"
                                source = "sensor"
                                break
                            
                            # Now safe to check is_stale and use age_seconds
                            if sensor_is_stale:
                                pending = True
                                # Safely coerce age_seconds to int (should never be None, but defensive)
                                if sensor_age_seconds is None:
                                    sensor_age_seconds = 0
                                sensor_age_seconds = int(sensor_age_seconds)
                                age_min = sensor_age_seconds // 60
                                pending_reason = "sensor_stale"
                                pending_message = f"No valid temperature reading for {age_min} minute{'s' if age_min != 1 else ''}. Relay forced OFF for safety."
                                source = "sensor"
                                break
                
                except Exception as rule_err:
                    # Don't let one bad rule crash the whole pending state check
                    rule_id_str = rule.get("id", "unknown") if isinstance(rule, dict) else "unknown"
                    print(f"[_get_relay_pending_state] Eval error for rule {rule_id_str}: {rule_err}")
                    continue  # Skip this rule, check others
            
            # Check cooldown (only if sensor is OK)
            if not pending:
                for rule in enabled_rules:
                    # Double-check rule is dict (should be, but be defensive)
                    if not isinstance(rule, dict):
                        continue
                    
                    try:
                        last_triggered = rule.get("last_triggered_at")
                        if last_triggered:
                            age = now - last_triggered
                            cooldown_sec = rule.get("cooldown_seconds", 60)
                            if age < cooldown_sec:
                                pending = True
                                pending_reason = "cooldown"
                                cooldown_remaining = cooldown_sec - age
                                pending_message = f"Cooldown active: {cooldown_remaining}s remaining"
                                source = "rule"
                                break
                    except Exception as cooldown_err:
                        # Don't let one bad rule crash cooldown check
                        rule_id_str = rule.get("id", "unknown") if isinstance(rule, dict) else "unknown"
                        print(f"[_get_relay_pending_state] Cooldown check error for rule {rule_id_str}: {cooldown_err}")
                        continue
        
        # Ensure source is always defined
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
        # NEVER throw - always return safe defaults
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

