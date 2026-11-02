"""
Remote desired_state sync from Supabase.
Polls device_settings and applies relay changes locally when version advances.
"""
from __future__ import annotations

import time
import json
import threading
from typing import Any, Dict, Optional, Tuple, List

import requests

from smartify.logging_setup import logger
from smartify import state
from smartify.config import (
    SMARTIFY_SUPABASE_URL,
    SMARTIFY_SUPABASE_SERVICE_KEY,
    SMARTIFY_DEVICE_ID,
    SMARTIFY_REMOTE_SYNC_ENABLED,
    SMARTIFY_REMOTE_SYNC_INTERVAL_SECONDS,
)
from smartify.db import (
    db_list_relay_devices,
    db_get_relay_state_new,
    db_get_relay_device_by_name,
    db_update_relay_state_new,
)
from smartify.services.relays import apply_relay_hardware, reconcile_relay


HTTP_TIMEOUT_SECONDS = 5


def _clamp_interval(seconds: int) -> int:
    try:
        value = int(seconds)
    except Exception:
        value = 10
    return min(15, max(5, value))


def _update_status(**updates: Any) -> None:
    state._remote_sync_status.update(updates)


def _supabase_headers() -> Dict[str, str]:
    return {
        "Content-Type": "application/json",
        "apikey": SMARTIFY_SUPABASE_SERVICE_KEY,
        "Authorization": f"Bearer {SMARTIFY_SUPABASE_SERVICE_KEY}",
    }


def _supabase_base_url() -> str:
    return SMARTIFY_SUPABASE_URL.rstrip("/")


def fetch_device_settings() -> Optional[Dict[str, Any]]:
    if not SMARTIFY_SUPABASE_URL or not SMARTIFY_SUPABASE_SERVICE_KEY or not SMARTIFY_DEVICE_ID:
        return None

    url = f"{_supabase_base_url()}/rest/v1/device_settings"
    params = {
        "device_id": f"eq.{SMARTIFY_DEVICE_ID}",
        "select": "desired_state,version,updated_at",
        "limit": "1",
    }
    resp = requests.get(url, headers=_supabase_headers(), params=params, timeout=HTTP_TIMEOUT_SECONDS)
    if resp.status_code >= 400:
        raise RuntimeError(f"device_settings fetch failed: {resp.status_code} {resp.text[:200]}")
    data = resp.json()
    return data[0] if data else None


def fetch_device_state() -> Optional[Dict[str, Any]]:
    if not SMARTIFY_SUPABASE_URL or not SMARTIFY_SUPABASE_SERVICE_KEY or not SMARTIFY_DEVICE_ID:
        return None

    url = f"{_supabase_base_url()}/rest/v1/device_state"
    params = {
        "device_id": f"eq.{SMARTIFY_DEVICE_ID}",
        "select": "applied_version,current_state,last_seen",
        "limit": "1",
    }
    resp = requests.get(url, headers=_supabase_headers(), params=params, timeout=HTTP_TIMEOUT_SECONDS)
    if resp.status_code >= 400:
        raise RuntimeError(f"device_state fetch failed: {resp.status_code} {resp.text[:200]}")
    data = resp.json()
    return data[0] if data else None


def upsert_device_state(payload: Dict[str, Any]) -> None:
    if not SMARTIFY_SUPABASE_URL or not SMARTIFY_SUPABASE_SERVICE_KEY or not SMARTIFY_DEVICE_ID:
        return

    url = f"{_supabase_base_url()}/rest/v1/device_state"
    headers = _supabase_headers()
    headers["Prefer"] = "resolution=merge-duplicates,return=minimal"
    resp = requests.post(url, headers=headers, json=payload, timeout=HTTP_TIMEOUT_SECONDS)
    if resp.status_code >= 400:
        raise RuntimeError(f"device_state upsert failed: {resp.status_code} {resp.text[:200]}")


def _relay_actual_state(relay_id: str) -> str:
    relay_state = db_get_relay_state_new(relay_id)
    if not relay_state:
        return "off"
    return relay_state.get("actual_state") or relay_state.get("desired_state") or relay_state.get("state", "off")


def _build_current_state() -> Dict[str, Any]:
    relays = db_list_relay_devices()
    relays_state: Dict[str, str] = {}
    for relay in relays:
        relays_state[relay["name"]] = _relay_actual_state(relay["id"])
    return {
        "relays": relays_state,
        "source": "kombi",
    }


def _apply_manual_relay(relay_id: str, state_value: str) -> Tuple[bool, Optional[str]]:
    now_ts = int(time.time())
    db_update_relay_state_new(
        relay_id=relay_id,
        mode="manual",
        manual_state=state_value,
        manual_until=None,
    )

    result = apply_relay_hardware(relay_id, state_value)
    if not result.get("ok"):
        return False, result.get("message") or result.get("error") or "hardware_failed"

    db_update_relay_state_new(
        relay_id,
        actual_state=state_value,
        desired_state=state_value,
        last_applied_at=now_ts,
    )

    try:
        reconcile_relay(relay_id, force=True)
    except Exception as exc:
        logger.warning("[RemoteSync] Reconcile failed for relay %s: %s", relay_id, exc)

    return True, None


def _apply_auto_relay(relay_id: str) -> Tuple[bool, Optional[str]]:
    db_update_relay_state_new(relay_id=relay_id, mode="auto")
    try:
        reconcile_relay(relay_id, force=True)
    except Exception as exc:
        return False, str(exc)
    return True, None


def apply_desired_state(desired_state: Dict[str, Any]) -> Tuple[int, List[str]]:
    changes = 0
    errors: List[str] = []

    # Generic relays map: {"relays": {"heater": "on"}}
    relays_payload = desired_state.get("relays")
    if isinstance(relays_payload, dict):
        for relay_name, relay_value in relays_payload.items():
            if relay_value not in ("on", "off", "auto"):
                continue
            relay = db_get_relay_device_by_name(str(relay_name))
            if not relay:
                continue
            relay_id = relay["id"]
            if relay_value == "auto":
                ok, err = _apply_auto_relay(relay_id)
            else:
                ok, err = _apply_manual_relay(relay_id, relay_value)
            if ok:
                changes += 1
            elif err:
                errors.append(f"{relay_name}: {err}")

    # Heater-specific compatibility (current dashboard)
    heater_force = desired_state.get("heater_force")
    heater_auto = desired_state.get("heater_auto")
    if heater_force in ("on", "off") or heater_auto is True:
        relay = db_get_relay_device_by_name("heater")
        if relay:
            relay_id = relay["id"]
            if heater_force in ("on", "off"):
                ok, err = _apply_manual_relay(relay_id, heater_force)
            else:
                ok, err = _apply_auto_relay(relay_id)
            if ok:
                changes += 1
            elif err:
                errors.append(f"heater: {err}")

    return changes, errors


def _sync_once() -> None:
    if not SMARTIFY_SUPABASE_URL or not SMARTIFY_SUPABASE_SERVICE_KEY or not SMARTIFY_DEVICE_ID:
        _update_status(last_error="Missing Supabase config or device id")
        return

    settings = fetch_device_settings()
    if not settings:
        _update_status(last_error="No device_settings found")
        return

    desired_state = settings.get("desired_state") or {}
    desired_version = int(settings.get("version") or 0)

    device_state = fetch_device_state() or {}
    applied_version = int(device_state.get("applied_version") or 0)
    current_state = device_state.get("current_state") or {}

    _update_status(
        last_desired_version=desired_version,
        last_applied_version=applied_version,
    )

    if desired_version <= applied_version:
        return

    changes, errors = apply_desired_state(desired_state)

    now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    if errors:
        current_state.update({
            "pending_reason": "apply_failed",
            "last_error": "; ".join(errors)[:500],
            "applied_at": now_iso,
        })
        upsert_device_state({
            "device_id": SMARTIFY_DEVICE_ID,
            "current_state": current_state,
            "last_seen": now_iso,
        })
        _update_status(last_error=current_state.get("last_error"), last_change_count=0)
        return

    current_state.update(_build_current_state())
    current_state.update({
        "applied_at": now_iso,
        "pending_reason": None,
        "last_error": None,
    })

    upsert_device_state({
        "device_id": SMARTIFY_DEVICE_ID,
        "applied_version": desired_version,
        "current_state": current_state,
        "last_seen": now_iso,
    })

    _update_status(
        last_success_ts=int(time.time()),
        last_error=None,
        last_applied_version=desired_version,
        last_change_count=changes,
    )


def _remote_sync_loop() -> None:
    interval = _clamp_interval(SMARTIFY_REMOTE_SYNC_INTERVAL_SECONDS)
    logger.info("[RemoteSync] Starting loop (interval=%ss)", interval)

    while True:
        _update_status(last_poll_ts=int(time.time()))
        try:
            _sync_once()
        except Exception as exc:
            logger.error("[RemoteSync] Error: %s", exc)
            _update_status(last_error=str(exc)[:500])
        time.sleep(interval)


def start_remote_sync_thread() -> None:
    if not SMARTIFY_REMOTE_SYNC_ENABLED:
        logger.info("[RemoteSync] Disabled (SMARTIFY_REMOTE_SYNC_ENABLED=false)")
        return

    t = threading.Thread(target=_remote_sync_loop, daemon=True, name="RemoteSync")
    t.start()
