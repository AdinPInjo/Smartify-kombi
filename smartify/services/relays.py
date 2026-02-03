"""
Relay control business logic.
"""
from typing import Dict, Any, Optional


def apply_relay_hardware(relay_id: str, state: str) -> Dict[str, Any]:
    # Lazy import to avoid circular dependency at module load
    from smartify.app import apply_relay_hardware as _apply
    return _apply(relay_id, state)


def reconcile_relay(relay_id: str, force: bool = False) -> bool:
    # Lazy import to avoid circular dependency at module load
    from smartify.app import reconcile_relay as _reconcile
    return _reconcile(relay_id, force)


def public_relay_mode(relay_state: Optional[Dict[str, Any]]) -> str:
    """Map internal mode/manual_state to public mode (off/on/auto)."""
    if not relay_state:
        return "auto"
    mode = relay_state.get("mode", "auto")
    if mode == "auto":
        return "auto"
    manual_state = relay_state.get("manual_state") or relay_state.get("desired_state") or relay_state.get("state")
    return manual_state if manual_state in ("on", "off") else "off"
