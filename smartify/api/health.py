"""Health and authentication status endpoints."""

from typing import Optional
from fastapi import APIRouter, Request, Header
from fastapi.responses import JSONResponse
import smartify.config as config
from smartify.auth import is_authenticated


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

    return router


# Default router for backward compatibility
router = create_health_router(
    is_authenticated,
    config.SMARTIFY_REQUIRE_AUTH,
    bool(config.SMARTIFY_API_KEY),
    config.SMARTIFY_TRUST_LOCALHOST,
)
