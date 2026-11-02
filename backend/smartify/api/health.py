from __future__ import annotations

import time

from fastapi import APIRouter, Request
from pydantic import BaseModel

from smartify import __version__
from smartify.db import connect, current_version

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    ok: bool
    version: str
    hardware: str
    schema_version: int
    server_time: int


@router.get("/health", response_model=HealthResponse)
def health(request: Request) -> HealthResponse:
    settings = request.app.state.settings
    conn = connect(settings.db_path)
    try:
        schema_version = current_version(conn)
    finally:
        conn.close()
    return HealthResponse(
        ok=True,
        version=__version__,
        hardware=settings.hardware,
        schema_version=schema_version,
        server_time=int(time.time()),
    )
