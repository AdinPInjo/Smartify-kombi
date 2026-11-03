"""Scenes: switch several relays with one tap."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, status
from pydantic import BaseModel, Field

from smartify.api.deps import Ctx, User
from smartify.services.scenes import ICONS

router = APIRouter(tags=["scenes"])


@router.get("/scenes")
def list_scenes(ctx: Ctx, _: User) -> dict:
    return {"scenes": [asdict(s) for s in ctx.scenes.list()], "icons": list(ICONS)}


class SceneBody(BaseModel):
    name: str = Field(max_length=30)
    icon: str = "star"
    actions: dict[str, str]


class SceneChanges(BaseModel):
    name: str | None = Field(default=None, max_length=30)
    icon: str | None = None
    actions: dict[str, str] | None = None
    position: int | None = None


@router.post("/scenes", status_code=status.HTTP_201_CREATED)
def create_scene(body: SceneBody, ctx: Ctx, _: User) -> dict:
    return asdict(ctx.scenes.create(body.name, body.icon, body.actions))


@router.patch("/scenes/{scene_id}")
def update_scene(scene_id: int, body: SceneChanges, ctx: Ctx, _: User) -> dict:
    changes: dict[str, Any] = body.model_dump(exclude_none=True)
    return asdict(ctx.scenes.update(scene_id, changes))


@router.delete("/scenes/{scene_id}")
def delete_scene(scene_id: int, ctx: Ctx, _: User) -> dict:
    ctx.scenes.delete(scene_id)
    return {"ok": True}


@router.post("/scenes/{scene_id}/run")
def run_scene(scene_id: int, ctx: Ctx, _: User) -> dict:
    return ctx.scenes.run(scene_id)
