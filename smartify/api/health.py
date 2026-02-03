"""Health and authentication status endpoints."""

from typing import Optional
from fastapi import APIRouter, Request, Header
from fastapi.responses import JSONResponse
import smartify.config as config
from smartify.auth import is_authenticated


router = APIRouter()


@router.get("/api/me")
def api_me(request: Request, x_api_key: Optional[str] = Header(default=None, alias="X-API-Key")):
    """Get current authentication status and user info."""
    authed = is_authenticated(request, x_api_key)
    return JSONResponse({
        "authenticated": authed,
        "user": request.session.get("user") if authed else None,
        "require_auth": config.SMARTIFY_REQUIRE_AUTH,
        "api_key_enabled": bool(config.SMARTIFY_API_KEY),
        "trusted_localhost": config.SMARTIFY_TRUST_LOCALHOST,
    })

