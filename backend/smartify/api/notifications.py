"""Push notification setup: channels, alerts, test messages and history."""

from __future__ import annotations

import time
from typing import Any, Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from smartify.api.deps import Ctx, User
from smartify.services.notify import new_topic

router = APIRouter(tags=["notifications"])

_SECRET_FIELDS = (("telegram", "bot_token"), ("ntfy", "token"))


def _view(ctx: Ctx) -> dict[str, Any]:
    return {
        **ctx.notifications.public_settings(),
        "active_channels": ctx.notifications.active_channels(),
    }


@router.get("/notifications/settings")
def get_settings(ctx: Ctx, _: User) -> dict:
    return _view(ctx)


@router.patch("/notifications/settings")
def update_settings(body: dict[str, Any], ctx: Ctx, _: User) -> dict:
    """Partial update, e.g. ``{"alerts": {"battery_low": {"threshold": 25}}}``.

    The dashboard never receives the secret tokens, so an empty token in an
    update means "keep the stored one" and ``null`` removes it.
    """
    channels = body.get("channels")
    if isinstance(channels, dict):
        for channel, key in _SECRET_FIELDS:
            section = channels.get(channel)
            if isinstance(section, dict):
                section.pop(f"{key}_set", None)
                if section.get(key) == "":
                    section.pop(key)
                elif key in section and section[key] is None:
                    section[key] = ""
    ctx.notifications.update_settings(body)
    return _view(ctx)


@router.post("/notifications/ntfy/new-topic")
def regenerate_topic(ctx: Ctx, _: User) -> dict:
    """A fresh random topic, e.g. when the old one was shared by accident."""
    ctx.notifications.update_settings({"channels": {"ntfy": {"topic": new_topic()}}})
    return _view(ctx)


class TestRequest(BaseModel):
    channel: Literal["ntfy", "telegram"]


@router.post("/notifications/test")
def send_test(body: TestRequest, ctx: Ctx, _: User) -> dict:
    ctx.notifications.send_test(body.channel)
    return {"ok": True}


@router.post("/notifications/telegram/detect-chat")
def detect_chat(ctx: Ctx, _: User) -> dict:
    return {**ctx.notifications.detect_telegram_chat(), "settings": _view(ctx)}


class PauseRequest(BaseModel):
    hours: float = Field(ge=0, le=72)
    """0 ends the pause."""


@router.post("/notifications/departure/pause")
def pause_departure(body: PauseRequest, ctx: Ctx, _: User) -> dict:
    """ "I'm driving": no departure alerts for a while."""
    until = int(time.time() + body.hours * 3600) if body.hours else None
    ctx.notifications.update_settings({"alerts": {"departure": {"paused_until": until}}})
    return _view(ctx)


@router.get("/notifications")
def history(ctx: Ctx, _: User, limit: int = Query(30, ge=1, le=200)) -> dict:
    return {"notifications": ctx.notifications.recent(limit)}
