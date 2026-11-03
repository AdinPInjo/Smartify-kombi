"""Device side of the remote sync, against a fake cloud."""

from __future__ import annotations

import pytest

from smartify.services.cloud_sync import HISTORY_BATCH, CloudError, CloudSync, apply_command
from smartify.services.snapshot import build_state


class FakeCloud:
    def __init__(self) -> None:
        self.requests: list[dict] = []
        self.commands: list[dict] = []
        self.fail = False

    def __call__(self, url, body, token):
        assert url == "https://cloud.example/api/device/sync"
        assert token == "secret"
        if self.fail:
            raise CloudError("cloud unreachable")
        self.requests.append(body)
        accepted = {table: rows[-1]["id"] for table, rows in (body.get("history") or {}).items()}
        commands = [c for c in self.commands if c["id"] > body["last_command_id"]]
        return {"commands": commands, "accepted": accepted, "server_time": 0}


class Clock:
    def __init__(self) -> None:
        self.now = 1_700_000_000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def sync(ctx):
    cloud, clock = FakeCloud(), Clock()
    service = CloudSync(
        url="https://cloud.example/",
        token="secret",
        db_path=ctx.settings.db_path,
        state_seconds=60,
        build_state=lambda: build_state(ctx),
        apply_command=lambda command: apply_command(ctx, command),
        transport=cloud,
        clock=clock,
    )
    return service, cloud, clock


def heater(ctx):
    return next(r for r in ctx.relays.list() if r.name == "heater")


def test_state_and_history_are_uploaded_then_only_polls(sync, ctx):
    service, cloud, clock = sync
    ctx.relays.set_manual(heater(ctx).id, "on")  # creates a relay event
    service.tick()
    first = cloud.requests[-1]
    assert {r["name"] for r in first["state"]["relays"]} == {"heater", "fan"}
    assert first["history"]["relay_events"]
    assert "energy" in first["state"] and "rules" in first["state"]

    clock.now += 10
    service.tick()
    assert "state" not in cloud.requests[-1]  # just polling for commands

    clock.now += 60
    service.tick()
    assert cloud.requests[-1]["history"] == {}  # history already accepted


def test_remote_switch_command_is_applied_once(sync, ctx):
    service, cloud, _ = sync
    relay = heater(ctx)
    cloud.commands = [
        {
            "id": 1,
            "type": "relay_manual",
            "target": relay.id,
            "payload": {"state": "on", "duration_minutes": 30},
        }
    ]
    service.tick()
    applied = ctx.relays.get(relay.id)
    assert applied.state == "on" and applied.source == "remote"
    assert applied.manual_until is not None

    service.tick()  # result reported; command not applied again
    assert cloud.requests[-1]["results"] == [{"id": 1, "ok": True, "status": "done", "error": None}]
    assert "state" in cloud.requests[-1]  # new state sent right after a command
    service.tick()
    assert cloud.requests[-1]["results"] == []


def test_settings_command_with_stale_revision_is_rejected(sync, ctx):
    service, cloud, _ = sync
    relay = heater(ctx)
    ctx.relays.update(relay.id, {"label": "Changed on the van"})
    cloud.commands = [
        {
            "id": 7,
            "type": "relay_update",
            "target": relay.id,
            "payload": {"label": "Changed remotely"},
            "base_revision": relay.revision,  # what the remote dashboard saw
        }
    ]
    service.tick()
    service.tick()
    result = cloud.requests[-1]["results"][0]
    assert result["status"] == "rejected" and "van's change wins" in result["error"]
    assert ctx.relays.get(relay.id).label == "Changed on the van"


def test_rule_commands(sync, ctx):
    service, cloud, _ = sync
    relay = heater(ctx)
    rule = {
        "name": "Heat",
        "condition": {
            "type": "threshold",
            "metric": "temperature",
            "sensor": "inside",
            "op": "<",
            "value": 8,
        },
        "action": "on",
    }
    cloud.commands = [
        {"id": 1, "type": "rule_create", "target": relay.id, "payload": rule},
        {
            "id": 2,
            "type": "rule_create",
            "target": relay.id,
            "payload": {**rule, "action": "maybe"},
        },
    ]
    service.tick()
    created = ctx.rules.list(relay.id)
    assert len(created) == 1
    service.tick()
    results = {r["id"]: r for r in cloud.requests[-1]["results"]}
    assert results[1]["ok"] and not results[2]["ok"]

    cloud.commands = [
        {
            "id": 3,
            "type": "rule_delete",
            "target": created[0].id,
            "payload": {},
            "base_revision": created[0].revision,
        }
    ]
    service.tick()
    assert ctx.rules.list(relay.id) == []


def test_failed_exchange_keeps_results_for_next_time(sync, ctx):
    service, cloud, clock = sync
    cloud.commands = [{"id": 1, "type": "relay_auto", "target": heater(ctx).id, "payload": {}}]
    service.tick()
    cloud.fail = True
    with pytest.raises(CloudError):
        service.tick()
    assert service.status.last_error
    cloud.fail = False
    clock.now += 1
    service.tick()
    assert cloud.requests[-1]["results"][0]["id"] == 1
    assert service.status.last_error is None


def test_large_history_is_sent_in_batches(sync, ctx):
    from smartify.db import transaction

    service, cloud, clock = sync
    with transaction(ctx.settings.db_path) as conn:
        conn.executemany(
            "INSERT INTO sensor_samples (sensor, temperature_c, humidity, ok, created_at) "
            "VALUES ('inside', 1, 1, 1, ?)",
            [(i,) for i in range(HISTORY_BATCH + 20)],
        )
    service.tick()
    assert len(cloud.requests[-1]["history"]["sensor_samples"]) == HISTORY_BATCH
    clock.now += 10
    service.tick()  # the rest follows on the next tick, not after a minute
    assert len(cloud.requests[-1]["history"]["sensor_samples"]) == 20
