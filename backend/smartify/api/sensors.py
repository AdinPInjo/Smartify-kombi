"""Climate (DHT22), water level + battery, GPS and weather."""

from __future__ import annotations

import time
from dataclasses import asdict
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from smartify.api.deps import Ctx, User
from smartify.services.gps_archive import archive_dir, is_archive_name, list_archives

router = APIRouter(tags=["sensors"])

Hours = Query(24, ge=1, le=24 * 90)


def _since(hours: int) -> int:
    return int(time.time()) - hours * 3600


# --- climate -----------------------------------------------------------------


@router.get("/climate")
def climate(ctx: Ctx, _: User) -> dict:
    return {"sensors": [asdict(s) for s in ctx.climate.snapshots()]}


@router.get("/climate/{sensor}/history")
def climate_history(sensor: str, ctx: Ctx, _: User, hours: int = Hours) -> dict:
    if sensor not in ctx.climate.sensor_names:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"sensor {sensor} not found")
    return {"sensor": sensor, "points": ctx.climate.history(sensor, _since(hours))}


# --- water + battery ------------------------------------------------------------


class WaterSettingsUpdate(BaseModel):
    method: Literal["voltage", "ratio"] | None = None
    signal_channel: int | None = Field(None, ge=0, le=3)
    supply_channel: int | None = Field(None, ge=0, le=3)
    divider_r_top: float | None = Field(None, gt=0)
    divider_r_bottom: float | None = Field(None, gt=0)
    empty_voltage: float | None = Field(None, ge=0, le=6.144)
    full_voltage: float | None = Field(None, ge=0, le=6.144)
    empty_ratio: float | None = Field(None, gt=0, lt=1)
    full_ratio: float | None = Field(None, gt=0, lt=1)


class CalibrateRequest(BaseModel):
    point: Literal["empty", "full"]


@router.get("/water")
def water(ctx: Ctx, _: User) -> dict:
    return asdict(ctx.water.current())


@router.get("/water/history")
def water_history(ctx: Ctx, _: User, hours: int = Hours) -> dict:
    return {"points": ctx.water.history(_since(hours))}


@router.get("/water/settings")
def water_settings(ctx: Ctx, _: User) -> dict:
    return asdict(ctx.water.settings())


@router.patch("/water/settings")
def update_water_settings(body: WaterSettingsUpdate, ctx: Ctx, _: User) -> dict:
    changes = {k: v for k, v in body.model_dump(exclude_unset=True).items() if v is not None}
    return asdict(ctx.water.update_settings(changes))


@router.post("/water/calibrate")
def calibrate_water(body: CalibrateRequest, ctx: Ctx, _: User) -> dict:
    """Use the current reading as the empty or full point (fill/empty the tank first)."""
    return asdict(ctx.water.calibrate(body.point))


# --- GPS -----------------------------------------------------------------------


@router.get("/gps")
def gps(ctx: Ctx, _: User) -> dict:
    state = ctx.gps.state()
    return {
        "status": state.status,
        "fix": asdict(state.fix) if state.fix else None,
        "fix_at": state.fix_at,
        "error": state.error,
    }


@router.get("/gps/track")
def gps_track(ctx: Ctx, _: User, hours: int = Hours) -> dict:
    return {"points": ctx.gps.track(_since(hours))}


@router.get("/gps/archive")
def gps_archive_list(ctx: Ctx, _: User) -> dict:
    return {"files": list_archives(ctx.settings.data_dir)}


@router.get("/gps/archive/{name}")
def gps_archive_download(name: str, ctx: Ctx, _: User) -> FileResponse:
    path = archive_dir(ctx.settings.data_dir) / name
    if not is_archive_name(name) or not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "archive not found")
    return FileResponse(path, media_type="application/gpx+xml", filename=f"kombi-{name}")


@router.get("/gps/distance")
def gps_distance(ctx: Ctx, _: User, days: int = Query(30, ge=1, le=365)) -> dict:
    return {"total_km": ctx.gps.total_distance_km(), "days": ctx.gps.distance_by_day(days)}


# --- energy (Victron) ------------------------------------------------------------


@router.get("/energy")
def energy(ctx: Ctx, _: User) -> dict:
    return {
        **ctx.energy.summary(),
        "devices": [asdict(d) for d in ctx.energy.devices()],
    }


@router.get("/energy/history")
def energy_history(ctx: Ctx, _: User, hours: int = Hours) -> dict:
    return {"points": ctx.energy.history(_since(hours))}


# --- weather -------------------------------------------------------------------


@router.get("/weather")
def weather(ctx: Ctx, _: User) -> dict:
    return ctx.weather.current()


@router.get("/weather/history")
def weather_history(ctx: Ctx, _: User, hours: int = Hours) -> dict:
    return {"points": ctx.weather.history(_since(hours))}
