from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, HTTPException, status
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from smartify.api.deps import Ctx, User
from smartify.services.wifi import WifiError

router = APIRouter(prefix="/wifi", tags=["wifi"])


class ConnectRequest(BaseModel):
    ssid: str = Field(min_length=1, max_length=32)
    password: str | None = Field(None, max_length=63)


@router.get("")
async def wifi_status(ctx: Ctx, _: User) -> dict:
    return asdict(await run_in_threadpool(ctx.wifi.status))


@router.get("/networks")
async def wifi_networks(ctx: Ctx, _: User) -> dict:
    try:
        networks = await run_in_threadpool(ctx.wifi.scan)
    except WifiError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    return {"networks": [asdict(n) for n in networks]}


@router.post("/connect")
async def wifi_connect(body: ConnectRequest, ctx: Ctx, _: User) -> dict:
    """Join a network. If the browser reaches the Pi over WiFi, it may lose the connection."""
    try:
        await run_in_threadpool(ctx.wifi.connect, body.ssid, body.password or None)
    except WifiError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return asdict(await run_in_threadpool(ctx.wifi.status))
