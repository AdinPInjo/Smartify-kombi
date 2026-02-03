"""
Rule evaluation helpers for API endpoints.
"""
from typing import Dict, Any, Optional, List, Tuple

from smartify import rule_engine
from smartify.db import db_get_sensor_snapshot, db_list_relay_rules as _db_list_relay_rules
from smartify.services.sensors import get_sensor_snapshot as _get_snapshot
from smartify.services.sensors import SENSOR_LIVE_STATUS, _sensor_live_status_lock
from smartify.validators import validate_rule_action


def db_list_relay_rules(relay_id: str) -> List[Dict[str, Any]]:
    """
    List rules for a relay. Handles JSON parsing errors gracefully.
    Re-exports from smartify.db but adds validation.
    """
    # Get basic rules from db module
    rules = _db_list_relay_rules(relay_id)
    
    # Add validation to actions
    for r in rules:
        action_raw = r.get("action", "")
        ok, _err, normalized_action = validate_rule_action(action_raw)
        r["action"] = normalized_action if ok else action_raw
    
    return rules


def evaluate_single_rule(rule: Dict[str, Any], relay_id: str) -> Dict[str, Any]:
    """
    Evaluate a single rule and return its runtime status without applying hardware.
    """
    def _snapshot(sensor_name: str) -> Dict[str, Any]:
        return _get_snapshot(sensor_name, db_get_sensor_snapshot, SENSOR_LIVE_STATUS, _sensor_live_status_lock)
    
    return rule_engine.evaluate_single_rule(rule, _snapshot)


def evaluate_rules(
    relay_id: str,
    current_state: Optional[str] = None,
) -> Tuple[Optional[str], Optional[Dict[str, Any]], Optional[Dict[str, Any]], bool, Optional[str]]:
    """Evaluate rules for a relay using snapshot data (delegates to rule_engine)."""
    def _snapshot(sensor_name: str) -> Dict[str, Any]:
        return _get_snapshot(sensor_name, db_get_sensor_snapshot, SENSOR_LIVE_STATUS, _sensor_live_status_lock)
    
    rules = db_list_relay_rules(relay_id)
    return rule_engine.evaluate_rules(rules, _snapshot, current_state)
