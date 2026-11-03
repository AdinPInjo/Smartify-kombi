"""Settings → Updates: check, install a version, roll back."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from smartify.api.deps import Ctx, User

router = APIRouter(tags=["updates"])


@router.get("/updates")
def updates(ctx: Ctx, _: User) -> dict:
    return ctx.updates.view()


class UpdateSettings(BaseModel):
    mode: str = Field(pattern="^(off|notify|auto)$")


@router.patch("/updates/settings")
def update_settings(body: UpdateSettings, ctx: Ctx, _: User) -> dict:
    ctx.updates.set_mode(body.mode)
    return ctx.updates.view()


@router.post("/updates/check")
async def check_now(ctx: Ctx, _: User) -> dict:
    await run_in_threadpool(ctx.updates.check, True)
    return ctx.updates.view()


class InstallRequest(BaseModel):
    version: str = Field(pattern=r"^\d+\.\d+\.\d+$")


@router.post("/updates/install")
def install(body: InstallRequest, ctx: Ctx, _: User) -> dict:
    """Starts the updater; progress shows up in GET /updates (status)."""
    ctx.updates.install(body.version)
    return ctx.updates.view()
