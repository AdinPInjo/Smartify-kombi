"""
Relay control API endpoints.
"""
from typing import Optional

from fastapi import APIRouter, Request, Header
from fastapi.responses import JSONResponse

# Import from dedicated modules (no circular imports)
from smartify.auth import require_auth
from smartify.db import db_list_relay_devices, db_get_relay_state_new
from smartify.relay_state import _get_relay_pending_state


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
            
            result.append({
                "id": relay_id,
                "name": relay["name"],
                "pin": relay["pin"],
                "active_low": bool(relay.get("active_low", 0)),
                "state": hardware_state,
                "mode": state.get("mode", "auto") if state else "auto",
                "manual_until": state.get("manual_until") if state else None,
                "updated_at": state.get("updated_at") if state else None,
                "is_enabled": bool(relay.get("is_enabled", True)),
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

