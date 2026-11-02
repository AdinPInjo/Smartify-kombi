"""Shared FastAPI dependencies."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Request, status

from smartify.context import AppContext


def get_context(request: Request) -> AppContext:
    return request.app.state.ctx


def require_user(request: Request) -> str:
    user = request.session.get("user")
    if not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "login required")
    return user


Ctx = Annotated[AppContext, Depends(get_context)]
User = Annotated[str, Depends(require_user)]
