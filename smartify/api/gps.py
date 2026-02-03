"""
GPS tracking API endpoints.
"""
import time
from typing import Optional

from fastapi import APIRouter, Request, Header
from fastapi.responses import JSONResponse

from smartify import state
from smartify.auth import require_auth
from smartify.db import db_query_gps_since


router = APIRouter(tags=["gps"])


@router.get("/api/gps/current")
def api_gps_current(request: Request, x_api_key: Optional[str] = Header(default=None, alias="X-API-Key")):
    err = require_auth(request, x_api_key)
    if err:
        return err
    return JSONResponse(state._gps_latest)


@router.get("/api/gps/track")
def api_gps_track(
    request: Request,
    hours: Optional[int] = None,
    minutes: Optional[int] = None,
    limit: int = 2000,
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
):
    err = require_auth(request, x_api_key)
    if err:
        return err

    now = int(time.time())
    if minutes is not None:
        since = now - int(minutes) * 60
    elif hours is not None:
        since = now - int(hours) * 3600
    else:
        since = now - 24 * 3600

    limit = max(1, min(int(limit), 50000))
    rows = db_query_gps_since(since, limit=limit)
    return JSONResponse({"since": since, "now": now, "rows": rows})
