"""Shared FastAPI dependencies."""

from __future__ import annotations

import hashlib
import hmac
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status

from smartify.context import AppContext


def get_context(request: Request) -> AppContext:
    return request.app.state.ctx


def password_fingerprint(secret_key: str, password: str) -> str:
    """Stored in the session; changing the password invalidates every session."""
    return hmac.new(secret_key.encode(), password.encode(), hashlib.sha256).hexdigest()[:16]


def require_user(request: Request) -> str:
    user = request.session.get("user")
    fingerprint = request.session.get("pw")
    expected = request.app.state.session_fingerprint
    if not user or not fingerprint or not hmac.compare_digest(fingerprint, expected):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "login required")
    return user


Ctx = Annotated[AppContext, Depends(get_context)]
User = Annotated[str, Depends(require_user)]
