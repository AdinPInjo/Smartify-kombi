"""Connect the van to its remote dashboard (cloud/ on your own web hosting)."""

from __future__ import annotations

from dataclasses import asdict
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from smartify.api.deps import Ctx, User
from smartify.services.cloud_link import check_url, parse_code
from smartify.services.cloud_sync import CloudError

router = APIRouter(tags=["cloud"])


def _view(ctx: Ctx) -> dict:
    connection = ctx.cloud_connection()
    return {
        "connected": connection is not None,
        "source": connection.source if connection else None,
        "url": connection.url if connection else None,
        "status": asdict(ctx.cloud.status) if ctx.cloud else None,
    }


@router.get("/cloud")
def cloud_status(ctx: Ctx, _: User) -> dict:
    return _view(ctx)


class ConnectRequest(BaseModel):
    code: str | None = Field(default=None, max_length=2000)
    """The connection code from the remote dashboard's installer (SMK1-...)."""
    url: str | None = Field(default=None, max_length=500)
    token: str | None = Field(default=None, max_length=200)


def _explain(error: CloudError, url: str) -> str:
    text = str(error)
    host = urlparse(url).netloc or url
    if "invalid device token" in text or "HTTP 401" in text:
        return (
            "the remote dashboard does not accept this code. Maybe a newer one was made: "
            "copy the latest code from its Settings"
        )
    if "unreachable" in text:
        return f"cannot reach {host}. Does the van have internet, and is the address right?"
    if "HTTP 404" in text:
        return f"no remote dashboard found at {url}. Check the address (with its folder)"
    if "not installed" in text or "HTTP 503" in text:
        return "the remote dashboard is not installed yet: finish install.php first"
    return f"the remote dashboard answered with an error: {text}"


@router.post("/cloud")
async def connect(body: ConnectRequest, ctx: Ctx, _: User) -> dict:
    if body.code:
        url, token = parse_code(body.code)
    elif body.url and body.token:
        url, token = check_url(body.url), body.token.strip()
    else:
        raise HTTPException(422, "paste the connection code")
    try:
        await run_in_threadpool(ctx.connect_cloud, url, token)
    except CloudError as exc:
        raise HTTPException(422, _explain(exc, url)) from None
    return _view(ctx)


@router.delete("/cloud")
async def disconnect(ctx: Ctx, _: User) -> dict:
    await run_in_threadpool(ctx.disconnect_cloud)
    return _view(ctx)
