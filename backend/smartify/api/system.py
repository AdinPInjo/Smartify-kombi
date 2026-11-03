from __future__ import annotations

import os
import shutil
import time
from dataclasses import asdict

from fastapi import APIRouter, Query

from smartify import __version__
from smartify.api.deps import Ctx, User
from smartify.db import connect, current_version

router = APIRouter(tags=["system"])


@router.get("/health")
def health(ctx: Ctx) -> dict:
    """Public liveness check (no login), for monitoring and the install script."""
    conn = connect(ctx.settings.db_path)
    try:
        schema_version = current_version(conn)
    finally:
        conn.close()
    return {
        "ok": True,
        "version": __version__,
        "hardware": ctx.settings.hardware,
        "schema_version": schema_version,
        "server_time": int(time.time()),
    }


def _cpu_temperature() -> float | None:
    try:
        with open("/sys/class/thermal/thermal_zone0/temp") as f:
            return round(int(f.read().strip()) / 1000, 1)
    except (OSError, ValueError):
        return None


@router.get("/system")
def system_status(ctx: Ctx, _: User) -> dict:
    disk = shutil.disk_usage(ctx.settings.data_dir)
    db_size = sum(
        p.stat().st_size for p in ctx.settings.data_dir.glob(f"{ctx.settings.db_filename}*")
    )
    return {
        "version": __version__,
        "hardware": ctx.settings.hardware,
        "uptime_seconds": int(time.time() - ctx.started_at),
        "server_time": int(time.time()),
        "cpu_temperature_c": _cpu_temperature(),
        "load_average": os.getloadavg()[0] if hasattr(os, "getloadavg") else None,
        "disk_free_bytes": disk.free,
        "disk_total_bytes": disk.total,
        "database_bytes": db_size,
        "default_credentials": ctx.settings.uses_default_credentials,
        "workers": [asdict(w.status()) for w in ctx.workers],
        "cloud": asdict(ctx.cloud.status) if ctx.cloud else None,
    }


@router.get("/logs")
def logs(
    ctx: Ctx,
    _: User,
    limit: int = Query(200, ge=1, le=500),
    level: str = Query("INFO", pattern="^(DEBUG|INFO|WARNING|ERROR)$"),
    after_id: int = 0,
) -> dict:
    return {"logs": ctx.logs.recent(limit, level, after_id)}
