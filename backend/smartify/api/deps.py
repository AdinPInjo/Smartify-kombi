"""Shared FastAPI dependencies."""

from __future__ import annotations

import hmac
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status

from smartify.context import AppContext
from smartify.services.accounts import AccountService


def get_context(request: Request) -> AppContext:
    return request.app.state.ctx


def get_accounts(request: Request) -> AccountService:
    return request.app.state.accounts


def require_user(request: Request) -> str:
    accounts: AccountService = request.app.state.accounts
    if accounts.setup_required:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "setup required")
    user = request.session.get("user")
    fingerprint = request.session.get("pw")
    if not user or not fingerprint or not hmac.compare_digest(fingerprint, accounts.fingerprint()):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "login required")
    return user


Ctx = Annotated[AppContext, Depends(get_context)]
User = Annotated[str, Depends(require_user)]
Accounts = Annotated[AccountService, Depends(get_accounts)]
