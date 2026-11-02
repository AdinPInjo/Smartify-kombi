"""Health and authentication status endpoints."""

from typing import Optional
from pathlib import Path
import json
import time
from fastapi import APIRouter, Request, Header
from fastapi.responses import JSONResponse
import smartify.config as config
from smartify.auth import is_authenticated, require_auth
from smartify import state


def create_health_router(
    is_authenticated_func,
    require_auth_enabled: bool,
    api_key_enabled: bool,
    trust_localhost_enabled: bool,
) -> APIRouter:
    router = APIRouter()

    @router.get("/api/me")
    def api_me(request: Request, x_api_key: Optional[str] = Header(default=None, alias="X-API-Key")):
        """Get current authentication status and user info."""
        authed = is_authenticated_func(request, x_api_key)
        return JSONResponse({
            "authenticated": authed,
            "user": request.session.get("user") if authed else None,
            "require_auth": require_auth_enabled,
            "api_key_enabled": api_key_enabled,
            "trusted_localhost": trust_localhost_enabled,
        })

    @router.get("/api/health/db-integrity")
    def api_db_integrity_status():
        """Get last DB integrity check result."""
        status_path = Path(config.DATA_DIR) / "db_integrity_status.json"
        if not status_path.exists():
            return JSONResponse({
                "ok": False,
                "status": "unknown",
                "message": "No integrity status recorded yet",
                "result": "",
                "db_path": config.DB_PATH,
                "last_run_ts": None,
            })
        try:
            payload = json.loads(status_path.read_text(encoding="utf-8"))
        except Exception as exc:
            return JSONResponse({
                "ok": False,
                "status": "error",
                "message": f"Failed to read integrity status: {exc}",
                "result": "",
                "db_path": config.DB_PATH,
                "last_run_ts": None,
            })
        status = payload.get("status", "unknown")
        return JSONResponse({
            "ok": status == "ok",
            "status": status,
            "message": payload.get("message", ""),
            "result": payload.get("result", ""),
            "db_path": payload.get("db_path", config.DB_PATH),
            "last_run_ts": payload.get("last_run_ts"),
        })

    @router.get("/api/system/health")
    def api_system_health(request: Request, x_api_key: Optional[str] = Header(default=None, alias="X-API-Key")):
        """Get background thread health status."""
        err = require_auth(request, x_api_key)
        if err:
            return err

        now = int(time.time())
        threads = []
        for name, info in state._thread_health.items():
            last = info.get("last_heartbeat") or 0
            threads.append({
                "name": name,
                "status": info.get("status", "unknown"),
                "error": info.get("error"),
                "last_heartbeat": last or None,
                "age_seconds": (now - last) if last else None,
            })
        threads.sort(key=lambda x: x["name"])
        return JSONResponse({"now": now, "threads": threads})

    @router.get("/api/remote-sync/status")
    def api_remote_sync_status(request: Request, x_api_key: Optional[str] = Header(default=None, alias="X-API-Key")):
        """Get remote sync polling status."""
        err = require_auth(request, x_api_key)
        if err:
            return err

        return JSONResponse(state._remote_sync_status)

    return router


# Default router for backward compatibility
router = create_health_router(
    is_authenticated,
    config.SMARTIFY_REQUIRE_AUTH,
    bool(config.SMARTIFY_API_KEY),
    config.SMARTIFY_TRUST_LOCALHOST,
)
