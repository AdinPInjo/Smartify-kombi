from __future__ import annotations

from dataclasses import asdict
from typing import Any, Literal

from fastapi import APIRouter, Query, status
from pydantic import BaseModel, Field

from smartify.api.deps import Ctx, User
from smartify.services.relays import Relay
from smartify.services.rules import Rule

router = APIRouter(tags=["relays"])

Name = Field(pattern=r"^[a-z0-9_-]{1,32}$")


class RelayCreate(BaseModel):
    name: str = Name
    gpio_pin: int = Field(ge=0, le=27)
    label: str | None = Field(None, max_length=60)
    active_low: bool = False
    enabled: bool = True
    min_on_seconds: int = Field(0, ge=0, le=86400)
    min_off_seconds: int = Field(0, ge=0, le=86400)


class RelayUpdate(BaseModel):
    gpio_pin: int | None = Field(None, ge=0, le=27)
    label: str | None = Field(None, max_length=60)
    active_low: bool | None = None
    enabled: bool | None = None
    min_on_seconds: int | None = Field(None, ge=0, le=86400)
    min_off_seconds: int | None = Field(None, ge=0, le=86400)


class ManualRequest(BaseModel):
    state: Literal["on", "off"]
    duration_minutes: int | None = Field(None, ge=1, le=7 * 24 * 60)
    """Return to automatic control after this long. Omit to stay manual."""


class RuleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    condition: dict[str, Any]
    action: Literal["on", "off"]
    priority: int = Field(100, ge=0, le=1000)
    cooldown_seconds: int = Field(60, ge=0, le=86400)
    enabled: bool = True


class RuleUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=60)
    condition: dict[str, Any] | None = None
    action: Literal["on", "off"] | None = None
    priority: int | None = Field(None, ge=0, le=1000)
    cooldown_seconds: int | None = Field(None, ge=0, le=86400)
    enabled: bool | None = None


def relay_out(relay: Relay) -> dict:
    return asdict(relay)


def _rules_with_status(ctx, relay_id: str) -> list[dict]:
    decision = ctx.rules.decide(relay_id)
    statuses = {s.rule_id: s for s in decision.statuses}
    result = []
    for rule in ctx.rules.list(relay_id):
        data = asdict(rule)
        status_ = statuses.get(rule.id)
        data["status"] = (
            {
                "matched": status_.matched,
                "issue": status_.issue.value if status_.issue else None,
                "values": status_.values,
                "is_winner": status_.is_winner,
            }
            if status_
            else None  # disabled rules are not evaluated
        )
        result.append(data)
    return result


# --- relays ------------------------------------------------------------------


@router.get("/relays")
def list_relays(ctx: Ctx, _: User) -> dict:
    return {"relays": [relay_out(r) for r in ctx.relays.list()]}


@router.post("/relays", status_code=status.HTTP_201_CREATED)
def create_relay(body: RelayCreate, ctx: Ctx, _: User) -> dict:
    return relay_out(ctx.relays.create(**body.model_dump()))


@router.get("/relays/{relay_id}")
def get_relay(relay_id: str, ctx: Ctx, _: User) -> dict:
    return relay_out(ctx.relays.get(relay_id))


@router.patch("/relays/{relay_id}")
def update_relay(relay_id: str, body: RelayUpdate, ctx: Ctx, _: User) -> dict:
    # label may be cleared with null; every other field ignores null.
    changes = {
        k: v
        for k, v in body.model_dump(exclude_unset=True).items()
        if v is not None or k == "label"
    }
    return relay_out(ctx.relays.update(relay_id, changes))


@router.delete("/relays/{relay_id}")
def delete_relay(relay_id: str, ctx: Ctx, _: User) -> dict:
    return relay_out(ctx.relays.delete(relay_id))


@router.post("/relays/{relay_id}/manual")
def set_manual(relay_id: str, body: ManualRequest, ctx: Ctx, _: User) -> dict:
    duration = body.duration_minutes * 60 if body.duration_minutes else None
    return relay_out(ctx.relays.set_manual(relay_id, body.state, duration))


@router.post("/relays/{relay_id}/auto")
def set_auto(relay_id: str, ctx: Ctx, _: User) -> dict:
    return relay_out(ctx.relays.set_auto(relay_id))


@router.get("/relays/{relay_id}/events")
def relay_events(relay_id: str, ctx: Ctx, _: User, limit: int = Query(50, ge=1, le=500)) -> dict:
    return {"events": ctx.relays.events(relay_id, limit)}


# --- rules -------------------------------------------------------------------


@router.get("/relays/{relay_id}/rules")
def list_rules(relay_id: str, ctx: Ctx, _: User) -> dict:
    relay = ctx.relays.get(relay_id)
    decision = ctx.rules.decide(relay_id)
    return {
        "rules": _rules_with_status(ctx, relay_id),
        "decision": {"state": decision.state, "reason": decision.reason},
        "mode": relay.mode,
    }


@router.post("/relays/{relay_id}/rules", status_code=status.HTTP_201_CREATED)
def create_rule(relay_id: str, body: RuleCreate, ctx: Ctx, _: User) -> dict:
    rule = ctx.rules.create(relay_id, **body.model_dump())
    ctx.relays.reconcile(relay_id, force=True)
    return asdict(rule)


@router.patch("/rules/{rule_id}")
def update_rule(rule_id: str, body: RuleUpdate, ctx: Ctx, _: User) -> dict:
    changes = {k: v for k, v in body.model_dump(exclude_unset=True).items() if v is not None}
    rule: Rule = ctx.rules.update(rule_id, changes)
    ctx.relays.reconcile(rule.relay_id, force=True)
    return asdict(rule)


@router.delete("/rules/{rule_id}")
def delete_rule(rule_id: str, ctx: Ctx, _: User) -> dict:
    rule = ctx.rules.delete(rule_id)
    ctx.relays.reconcile(rule.relay_id, force=True)
    return asdict(rule)
