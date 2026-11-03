"""Scenes: one tap puts several relays into a chosen state."""

from __future__ import annotations

from smartify.services.cloud_sync import apply_command
from smartify.services.snapshot import build_state


def relay_ids(client) -> dict[str, str]:
    return {r["name"]: r["id"] for r in client.get("/api/relays").json()["relays"]}


def test_make_run_and_see_a_scene_active(client):
    ids = relay_ids(client)
    night = client.post(
        "/api/scenes",
        json={"name": "Night", "icon": "moon", "actions": {ids["heater"]: "on", ids["fan"]: "off"}},
    )
    assert night.status_code == 201, night.text
    scene = night.json()
    assert scene["active"] is False

    result = client.post(f"/api/scenes/{scene['id']}/run").json()
    assert sorted(result["applied"]) == sorted(ids.values()) and result["skipped"] == []
    relays = {r["name"]: r for r in client.get("/api/relays").json()["relays"]}
    assert relays["heater"]["mode"] == "manual" and relays["heater"]["manual_state"] == "on"
    assert relays["fan"]["manual_state"] == "off"
    assert relays["heater"]["source"] == "scene"
    assert client.get("/api/scenes").json()["scenes"][0]["active"] is True

    # Changing one relay by hand: the scene is no longer what's going on.
    client.post(f"/api/relays/{ids['fan']}/manual", json={"state": "on"})
    assert client.get("/api/scenes").json()["scenes"][0]["active"] is False


def test_auto_hands_relays_back_to_their_rules(client):
    ids = relay_ids(client)
    client.post(f"/api/relays/{ids['heater']}/manual", json={"state": "on"})
    morning = client.post(
        "/api/scenes", json={"name": "Rules", "icon": "sun", "actions": {ids["heater"]: "auto"}}
    ).json()
    client.post(f"/api/scenes/{morning['id']}/run")
    heater = next(r for r in client.get("/api/relays").json()["relays"] if r["id"] == ids["heater"])
    assert heater["mode"] == "auto"


def test_scenes_are_checked(client):
    ids = relay_ids(client)

    def make(**body):
        base = {"name": "X", "icon": "star", "actions": {ids["heater"]: "on"}}
        return client.post("/api/scenes", json={**base, **body})

    assert make(name="   ").status_code == 422
    assert make(icon="unicorn").status_code == 422
    assert make(actions={}).status_code == 422
    assert make(actions={"nope": "on"}).status_code == 422
    assert make(actions={ids["heater"]: "maybe"}).status_code == 422
    for i in range(8):
        assert make(name=f"Scene {i}").status_code == 201
    assert make(name="One too many").status_code == 409


def test_edit_delete_and_removed_relays(client):
    ids = relay_ids(client)
    scene = client.post(
        "/api/scenes", json={"name": "Away", "icon": "door", "actions": {ids["fan"]: "off"}}
    ).json()
    edited = client.patch(f"/api/scenes/{scene['id']}", json={"name": "Leaving"}).json()
    assert edited["name"] == "Leaving" and edited["actions"] == {ids["fan"]: "off"}

    client.delete(f"/api/relays/{ids['fan']}")
    result = client.post(f"/api/scenes/{scene['id']}/run").json()
    assert result["skipped"] == [ids["fan"]] and result["applied"] == []

    assert client.delete(f"/api/scenes/{scene['id']}").status_code == 200
    assert client.get("/api/scenes").json()["scenes"] == []
    assert client.post(f"/api/scenes/{scene['id']}/run").status_code == 404


def test_remote_dashboard_sees_and_runs_scenes(client, ctx):
    ids = relay_ids(client)
    scene = client.post(
        "/api/scenes", json={"name": "Night", "icon": "moon", "actions": {ids["heater"]: "on"}}
    ).json()
    assert build_state(ctx)["scenes"]["scenes"][0]["name"] == "Night"
    apply_command(ctx, {"type": "scene_run", "target": str(scene["id"]), "payload": {}})
    heater = ctx.relays.get(ids["heater"])
    assert heater.manual_state == "on" and heater.source == "remote"
