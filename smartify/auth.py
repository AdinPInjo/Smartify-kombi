"""Authentication helpers for Smartify API endpoints."""

from typing import Optional
from fastapi import Request
from fastapi.responses import JSONResponse
import smartify.config as config


def is_localhost(request: Request) -> bool:
    """Check if request is coming from localhost."""
    host = request.client.host if request.client else ""
    return host in ("127.0.0.1", "::1", "localhost")


def is_authenticated(request: Request, x_api_key: Optional[str]) -> bool:
    """Check if request is authenticated via session, API key, or localhost trust."""
    if not config.SMARTIFY_REQUIRE_AUTH:
        return True

    if config.SMARTIFY_TRUST_LOCALHOST and is_localhost(request):
        return True

    if request.session.get("logged_in") is True:
        return True

    if config.SMARTIFY_API_KEY and x_api_key and x_api_key.strip() == config.SMARTIFY_API_KEY:
        return True

    return False


def require_auth(request: Request, x_api_key: Optional[str]) -> Optional[JSONResponse]:
    """Return None if authenticated, otherwise return 401 response."""
    if is_authenticated(request, x_api_key):
        return None
    return JSONResponse({"error": "unauthorized"}, status_code=401)

