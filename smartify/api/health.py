"""
Health and authentication status endpoint.
"""
from typing import Optional

from fastapi import APIRouter, Request, Header
from fastapi.responses import JSONResponse


router = APIRouter(tags=["health"])


def create_health_router(
    is_authenticated_func,
    require_auth_enabled: bool,
    api_key_enabled: bool,
    trust_localhost_enabled: bool
):
    """
    Creates the health router with dependencies from app.py.
    
    Args:
        is_authenticated_func: The is_authenticated function from app.py
        require_auth_enabled: SMARTIFY_REQUIRE_AUTH value
        api_key_enabled: Whether SMARTIFY_API_KEY is set
        trust_localhost_enabled: SMARTIFY_TRUST_LOCALHOST value
    """
    
    @router.get("/api/me")
    def api_me(request: Request, x_api_key: Optional[str] = Header(default=None, alias="X-API-Key")):
        authed = is_authenticated_func(request, x_api_key)
        return JSONResponse({
            "authenticated": authed,
            "user": request.session.get("user") if authed else None,
            "require_auth": require_auth_enabled,
            "api_key_enabled": api_key_enabled,
            "trusted_localhost": trust_localhost_enabled,
        })
    
    return router

