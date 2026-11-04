"""Sensors tab: add, change, test and remove sensors from the catalog."""

from __future__ import annotations

import logging
import subprocess
import threading
import time
from typing import Any

from fastapi import APIRouter, status
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from smartify.api.deps import Ctx, User
from smartify.errors import DeviceUnavailable
from smartify.hardware.base import SensorConfig
from smartify.services import diagnose
from smartify.services.sensors import CLIMATE_KINDS, INPUT_KINDS, RESTART_KINDS

router = APIRouter(tags=["sensors"])
log = logging.getLogger(__name__)


def _status(ctx: Ctx, sensor: SensorConfig) -> dict[str, Any]:
    """What the sensor says right now, in a few words."""
    if sensor.kind in CLIMATE_KINDS:
        snapshot = next((s for s in ctx.climate.snapshots() if s.sensor == sensor.name), None)
        if snapshot is None:
            return {"ok": None, "text": "starting…"}
        if snapshot.status == "ready":
            humidity = f" · {snapshot.humidity:.0f} %" if snapshot.humidity is not None else ""
            return {"ok": True, "text": f"{snapshot.temperature_c:.1f} °C{humidity}"}
        if snapshot.status == "warming_up":
            return {"ok": None, "text": "first readings…"}
        return {"ok": False, "text": snapshot.last_error or "no readings"}
    if sensor.kind in INPUT_KINDS:
        state = next((s for s in ctx.inputs.states() if s["name"] == sensor.name), None)
        if state is None or (state["active"] is None and not state["error"]):
            return {"ok": None, "text": "starting…"}
        if state["active"] is None:
            return {"ok": False, "text": state["error"]}
        words = ("open", "closed") if sensor.kind == "door" else ("motion", "quiet")
        return {
            "ok": True,
            "text": words[0] if state["active"] else words[1],
            "active": state["active"],
        }
    if sensor.kind == "gps":
        if not ctx.gps.enabled:
            return {"ok": None, "text": "starts after a restart"}
        gps = ctx.gps.state()
        if gps.status == "ok" and gps.fix:
            return {"ok": True, "text": f"position · {gps.fix.satellites or '–'} satellites"}
        return {
            "ok": None if gps.status in ("no_fix", "waiting") else False,
            "text": gps.error or "searching for satellites…",
        }
    if sensor.kind == "water_tank":
        if not ctx.water.enabled:
            return {"ok": None, "text": "starts after a restart"}
        reading = ctx.water.current()
        if reading.ok:
            return {"ok": True, "text": f"{reading.level_percent} %"}
        return {"ok": False, "text": reading.error or "no reading yet"}
    return {"ok": None, "text": ""}


def _view(ctx: Ctx, sensor: SensorConfig) -> dict[str, Any]:
    return {
        "id": sensor.id,
        "name": sensor.name,
        "kind": sensor.kind,
        "config": sensor.config,
        "status": _status(ctx, sensor),
        "needs_restart": sensor.kind in RESTART_KINDS,
    }


@router.get("/sensors")
def list_sensors(ctx: Ctx, _: User) -> dict:
    return {
        "sensors": [_view(ctx, s) for s in ctx.sensor_store.all()],
        "restart_required": ctx.restart_required,
        "pins": ctx.sensor_store.pin_map(),
        "onewire_pin": ctx.sensor_store.onewire_pin(),
        "available": ctx.hardware.sensors is not None,
    }


@router.get("/sensors/discover")
async def discover(ctx: Ctx, _: User) -> dict:
    """1-Wire probes and I2C addresses found right now."""
    if ctx.hardware.sensors is None:
        raise DeviceUnavailable("sensors are not available on this Smartify")
    return await run_in_threadpool(ctx.hardware.sensors.discover)


class SensorBody(BaseModel):
    name: str = Field(max_length=24)
    kind: str = Field(max_length=20)
    config: dict[str, Any] = Field(default_factory=dict)


class SensorChanges(BaseModel):
    name: str | None = Field(default=None, max_length=24)
    config: dict[str, Any] | None = None


class TestBody(BaseModel):
    kind: str = Field(max_length=20)
    config: dict[str, Any] = Field(default_factory=dict)


@router.post("/sensors", status_code=status.HTTP_201_CREATED)
def add_sensor(body: SensorBody, ctx: Ctx, _: User) -> dict:
    sensor = ctx.sensor_store.add(body.name.strip(), body.kind, body.config)
    ctx.apply_sensors()
    return _view(ctx, sensor)


@router.patch("/sensors/{sensor_id}")
def change_sensor(sensor_id: str, body: SensorChanges, ctx: Ctx, _: User) -> dict:
    sensor = ctx.sensor_store.update(
        sensor_id, body.name.strip() if body.name else None, body.config
    )
    ctx.apply_sensors()
    return _view(ctx, sensor)


@router.delete("/sensors/{sensor_id}")
def remove_sensor(sensor_id: str, ctx: Ctx, _: User) -> dict:
    ctx.sensor_store.remove(sensor_id)
    ctx.apply_sensors()
    return {"ok": True, "restart_required": ctx.restart_required}


@router.post("/sensors/test")
async def test_sensor(body: TestBody, ctx: Ctx, _: User) -> dict:
    """Try a sensor before saving it: one live reading."""
    if ctx.hardware.sensors is None:
        raise DeviceUnavailable("sensors are not available on this Smartify")
    return await run_in_threadpool(ctx.hardware.sensors.test, body.kind, body.config)


@router.get("/sensors/{sensor_id}/diagnostics")
def diagnostics(sensor_id: str, ctx: Ctx, _: User) -> dict:
    """What the sensor read lately, and hints about the wiring."""
    sensor = ctx.sensor_store.get(sensor_id)
    result: dict[str, Any] = {
        "name": sensor.name,
        "kind": sensor.kind,
        "status": _status(ctx, sensor),
    }
    if sensor.kind in CLIMATE_KINDS:
        data = ctx.climate.diagnostics(sensor.name) or {"reads": 0, "good": 0, "recent": []}
        errors = [r["error"] for r in data["recent"] if r["error"]]
        result.update(data)
        result["hints"] = diagnose.climate_hints(
            sensor.kind, sensor.config, data["reads"], data["good"], errors
        )
    elif sensor.kind in INPUT_KINDS:
        data = ctx.inputs.diagnostics(sensor.name) or {
            "reads": 0,
            "good": 0,
            "active": None,
            "error": None,
            "changes": [],
        }
        result.update(data)
        result["hints"] = diagnose.input_hints(sensor.kind, sensor.config, data)
    elif sensor.kind == "gps":
        gps = ctx.gps.state()
        satellites = gps.fix.satellites if gps.fix else None
        result.update({"gps_status": gps.status, "satellites": satellites, "error": gps.error})
        result["hints"] = (
            diagnose.gps_hints(gps.status, satellites, gps.error)
            if ctx.gps.enabled
            else ["Starts after a restart."]
        )
    elif sensor.kind == "water_tank":
        result["hints"] = (
            diagnose.water_hints(ctx.water.current())
            if ctx.water.enabled
            else ["Starts after a restart."]
        )
    return result


class DebugBody(BaseModel):
    enabled: bool
    hours: float = Field(default=2, ge=0.25, le=24)


@router.get("/system/debug")
def debug_state(ctx: Ctx, _: User) -> dict:
    return ctx.debug.state()


@router.post("/system/debug")
def debug_set(body: DebugBody, ctx: Ctx, _: User) -> dict:
    return ctx.debug.set(body.enabled, body.hours)


@router.post("/system/restart")
def restart(ctx: Ctx, _: User) -> dict:
    """Restart Smartify (needed after GPS or water sender changes)."""
    if ctx.settings.hardware != "pi":
        return {"restarting": False, "message": "Simulation: nothing to restart."}

    def later() -> None:
        time.sleep(1)  # let this answer reach the browser first
        result = subprocess.run(
            ["systemctl", "--no-block", "restart", "smartify"], capture_output=True, text=True
        )
        if result.returncode != 0:
            log.error("Restart failed: %s", result.stderr.strip())

    threading.Thread(target=later, daemon=True).start()
    return {
        "restarting": True,
        "message": "Smartify restarts now; the dashboard is back in about 20 seconds.",
    }
