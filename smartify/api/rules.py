"""
Rules engine API endpoints.
"""
from typing import Optional, Dict, Any

from fastapi import APIRouter, Request, Header
from fastapi.responses import JSONResponse

from smartify.auth import require_auth
from smartify.db import db_get_relay_state_new
from smartify.services.rules import db_list_relay_rules, evaluate_rules, evaluate_single_rule
from smartify.utils import coerce_to_dict
from smartify.validators import validate_rule_condition


router = APIRouter(tags=["rules"])


@router.get("/api/relays/{relay_id}/rules")
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
            _, winner_rule, _winner_info, _sensor_ok, _reason = evaluate_rules(relay_id, current_actual)
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
