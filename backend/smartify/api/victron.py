"""Victron setup from the dashboard: find devices nearby, add them with their key."""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, status
from pydantic import BaseModel, Field

from smartify.api.deps import Ctx, User

router = APIRouter(tags=["victron"])


def _devices(ctx: Ctx) -> dict:
    live = {d.device: d for d in ctx.energy.devices()}
    devices = []
    for device in ctx.victron.configured():
        reading = live.get(device.name)
        devices.append(
            {
                **asdict(device),
                "kind": reading.kind if reading else None,
                "model": reading.model if reading else None,
                "rssi": reading.rssi if reading else None,
                "updated_at": reading.updated_at if reading else None,
                "status": "never" if reading is None else "stale" if reading.stale else "ok",
            }
        )
    return {
        "bluetooth": ctx.victron.available,
        "error": ctx.victron.error,
        "devices": devices,
    }


@router.get("/victron/devices")
def list_devices(ctx: Ctx, _: User) -> dict:
    return _devices(ctx)


@router.get("/victron/nearby")
def nearby(ctx: Ctx, _: User) -> dict:
    """Victron devices heard over Bluetooth in the last two minutes, strongest first."""
    return {
        "bluetooth": ctx.victron.available,
        "error": ctx.victron.error,
        "devices": ctx.victron.discovered(),
    }


class AddDevice(BaseModel):
    name: str = Field(max_length=32)
    mac: str = Field(max_length=32)
    key: str = Field(max_length=64)


@router.post("/victron/devices", status_code=status.HTTP_201_CREATED)
def add_device(body: AddDevice, ctx: Ctx, _: User) -> dict:
    added = ctx.victron.add(body.name, body.mac, body.key)
    return {**added, **_devices(ctx)}


@router.delete("/victron/devices/{name}")
def remove_device(name: str, ctx: Ctx, _: User) -> dict:
    ctx.victron.remove(name)
    ctx.energy.forget(name)
    return _devices(ctx)
