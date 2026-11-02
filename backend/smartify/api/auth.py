from __future__ import annotations

import asyncio
import secrets

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel

from smartify.api.deps import Ctx, User

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


@router.post("/login")
async def login(body: LoginRequest, request: Request, ctx: Ctx) -> dict:
    settings = ctx.settings
    valid_user = secrets.compare_digest(body.username.encode(), settings.username.encode())
    valid_pass = secrets.compare_digest(body.password.encode(), settings.password.encode())
    if not (valid_user and valid_pass):
        await asyncio.sleep(1)  # slows down password guessing
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "wrong username or password")
    request.session.clear()
    request.session["user"] = settings.username
    request.session["pw"] = request.app.state.session_fingerprint
    return {"user": settings.username}


@router.post("/logout")
def logout(request: Request) -> dict:
    request.session.clear()
    return {"ok": True}


@router.get("/me")
def me(user: User, ctx: Ctx) -> dict:
    return {"user": user, "default_credentials": ctx.settings.uses_default_credentials}
