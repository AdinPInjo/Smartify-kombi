"""
Relay control API endpoints.
"""
from typing import Optional, Dict, Any

from fastapi import APIRouter, Request, Header, Body
from fastapi.responses import JSONResponse

# Import from dedicated modules (no circular imports)
from smartify.auth import require_auth
from smartify.config import HEADER_RELAY_NAME, HEADER_RELAY_PIN, _relay_lock
from smartify.db import (
    db_list_relay_devices,
    db_get_relay_state_new,
    db_get_relay_events,
    db_get_relay_device_by_name,
    db_update_relay_state_new,
)
from smartify.relay_state import _get_relay_pending_state
from smartify.services.relays import apply_relay_hardware, reconcile_relay, public_relay_mode


router = APIRouter(tags=["relays"])


@router.get("/api/relays")
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
            
            result.append({
                "id": relay_id,
                "name": relay["name"],
                "pin": relay["pin"],
                "active_low": bool(relay.get("active_low", 0)),
                "state": hardware_state,
                "mode": public_relay_mode(state),
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


@router.get("/api/relays/{relay_id}/events")
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


@router.get("/api/relay/header")
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


@router.post("/api/relay/header")
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
