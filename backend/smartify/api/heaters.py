"""Diesel heaters over Bluetooth: find, add, switch, set temperature or power."""

from __future__ import annotations

from fastapi import APIRouter, status
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from smartify.api.deps import Ctx, User

router = APIRouter(tags=["heaters"])


@router.get("/heaters")
def list_heaters(ctx: Ctx, _: User) -> dict:
    return {"heaters": ctx.heaters.list(), "available": ctx.heaters.available}


@router.get("/heaters/nearby")
def nearby(ctx: Ctx, _: User) -> dict:
    return {"heaters": ctx.heaters.nearby()}


class AddHeater(BaseModel):
    name: str = Field(max_length=30)
    mac: str = Field(max_length=17)
    pin: int = Field(default=1234, ge=0, le=9999)


@router.post("/heaters", status_code=status.HTTP_201_CREATED)
def add_heater(body: AddHeater, ctx: Ctx, _: User) -> dict:
    return ctx.heaters.add(body.name, body.mac, body.pin)


class HeaterChanges(BaseModel):
    name: str | None = Field(default=None, max_length=30)
    pin: int | None = Field(default=None, ge=0, le=9999)


@router.patch("/heaters/{heater_id}")
def update_heater(heater_id: str, body: HeaterChanges, ctx: Ctx, _: User) -> dict:
    return ctx.heaters.update(heater_id, body.name, body.pin)


@router.delete("/heaters/{heater_id}")
def remove_heater(heater_id: str, ctx: Ctx, _: User) -> dict:
    ctx.heaters.remove(heater_id)
    return {"ok": True}


class Power(BaseModel):
    on: bool


@router.post("/heaters/{heater_id}/power")
async def power(heater_id: str, body: Power, ctx: Ctx, _: User) -> dict:
    return await run_in_threadpool(ctx.heaters.power, heater_id, body.on)


class Settings(BaseModel):
    mode: str | None = Field(default=None, pattern="^(temperature|level)$")
    temperature: float | None = None
    level: int | None = None


@router.post("/heaters/{heater_id}/settings")
async def heater_settings(heater_id: str, body: Settings, ctx: Ctx, _: User) -> dict:
    return await run_in_threadpool(
        ctx.heaters.settings, heater_id, body.mode, body.temperature, body.level
    )
