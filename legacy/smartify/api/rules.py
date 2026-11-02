"""
Rules engine API endpoints.
"""
from typing import Optional, Dict, Any

from fastapi import APIRouter, Request, Header, Body
from fastapi.responses import JSONResponse

from smartify.auth import require_auth
from smartify.db import (
    db_get_relay_state_new,
    db_get_relay_device,
    db_create_relay_rule,
    db_get_relay_rule,
    db_update_relay_rule,
    db_delete_relay_rule,
)
from smartify.services.rules import db_list_relay_rules, evaluate_rules, evaluate_single_rule
from smartify.services.relays import reconcile_relay
from smartify.utils import coerce_to_dict
from smartify.validators import validate_rule_condition, validate_rule_action


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


@router.post("/api/relays/{relay_id}/rules")
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


@router.post("/api/relays/{relay_id}/rules/temperature-band")
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


@router.post("/api/relays/{relay_id}/rules/humidity-band")
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


@router.put("/api/rules/{rule_id}")
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


@router.delete("/api/rules/{rule_id}")
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


@router.post("/api/rules/{rule_id}/toggle")
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
