from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from smartify.api.deps import Accounts, User

router = APIRouter(tags=["auth"])


class LoginRequest(BaseModel):
    username: str = Field(max_length=64)
    password: str = Field(max_length=256)


def _sign_in(request: Request, accounts: Accounts, username: str) -> None:
    request.session.clear()
    request.session["user"] = username
    request.session["pw"] = accounts.fingerprint()


@router.post("/auth/login")
async def login(body: LoginRequest, request: Request, accounts: Accounts) -> dict:
    if accounts.setup_required:
        raise HTTPException(status.HTTP_409_CONFLICT, "setup required: create the login first")
    if not await run_in_threadpool(accounts.verify, body.username, body.password):
        await asyncio.sleep(1)  # slows down password guessing
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "wrong username or password")
    _sign_in(request, accounts, body.username)
    return {"user": body.username}


@router.post("/auth/logout")
def logout(request: Request) -> dict:
    request.session.clear()
    return {"ok": True}


@router.get("/auth/me")
def me(user: User, accounts: Accounts) -> dict:
    return {
        "user": user,
        "default_credentials": accounts.uses_default_password,
        "login_source": accounts.source,
    }


# --- first-run setup -------------------------------------------------------------------


@router.get("/setup")
def setup_status(accounts: Accounts) -> dict:
    """Public: does the dashboard still need its first-run setup?"""
    return {"required": accounts.setup_required}


class SetupRequest(BaseModel):
    username: str = Field(default="admin", max_length=64)
    password: str = Field(max_length=256)


@router.post("/setup", status_code=status.HTTP_201_CREATED)
async def setup(body: SetupRequest, request: Request, accounts: Accounts) -> dict:
    """Create the login. Only works once, while no login exists; signs you in."""
    username = await run_in_threadpool(accounts.create, body.username, body.password)
    _sign_in(request, accounts, username)
    return {"user": username}


class PasswordChange(BaseModel):
    current_password: str = Field(max_length=256)
    new_password: str = Field(max_length=256)
    username: str | None = Field(default=None, max_length=64)


@router.post("/auth/password")
async def change_password(
    body: PasswordChange, request: Request, accounts: Accounts, _: User
) -> dict:
    """New password (and optionally username). Other devices are signed out; this one stays in."""
    username = await run_in_threadpool(
        accounts.change, body.current_password, body.new_password, body.username
    )
    _sign_in(request, accounts, username)
    return {"user": username}
