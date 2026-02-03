"""
Authentication and authorization helpers for Smartify.
"""
import os
from typing import Optional

from fastapi import Request
from fastapi.responses import JSONResponse


# Load auth config from environment
SMARTIFY_REQUIRE_AUTH = os.environ.get("SMARTIFY_REQUIRE_AUTH", "1").lower() not in ("0", "false", "no")
SMARTIFY_API_KEY = os.environ.get("SMARTIFY_API_KEY", "").strip()
SMARTIFY_TRUST_LOCALHOST = os.environ.get("SMARTIFY_TRUST_LOCALHOST", "0").lower() in ("1", "true", "yes")


def is_localhost(request: Request) -> bool:
    host = request.client.host if request.client else ""
    return host in ("127.0.0.1", "::1", "localhost")


def is_authenticated(request: Request, x_api_key: Optional[str]) -> bool:
    if not SMARTIFY_REQUIRE_AUTH:
        return True

    if SMARTIFY_TRUST_LOCALHOST and is_localhost(request):
        return True

    if request.session.get("logged_in") is True:
        return True

    if SMARTIFY_API_KEY and x_api_key and x_api_key.strip() == SMARTIFY_API_KEY:
        return True

    return False


def require_auth(request: Request, x_api_key: Optional[str]) -> Optional[JSONResponse]:
    if is_authenticated(request, x_api_key):
        return None
    return JSONResponse({"error": "unauthorized"}, status_code=401)

