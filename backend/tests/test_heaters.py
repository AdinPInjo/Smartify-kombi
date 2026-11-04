"""Diesel heaters over Bluetooth: protocols, setup, control, scenes, alerts."""

from __future__ import annotations

import pytest

from smartify.hardware import heater_protocol as hp
from smartify.hardware.base import HeaterLink
from smartify.services.cloud_sync import apply_command
from smartify.services.snapshot import build_state

MAC = "D4:8A:FC:10:20:30"


def aa55_status(
    *, on=True, step=3, mode=2, target=22, level=5, volts=12.8, case=120, cabin=19, error=0
):
    """A Vevor AA55 status notification, byte by byte (see ProtocolAA55.parse)."""
    data = bytearray(20)
    data[0:2] = b"\xaa\x55"
    data[3], data[4], data[5] = int(on), error, step
    data[8] = mode
    data[9] = target if mode == 2 else level
    data[10] = level - 1
    raw = round(volts * 10)
    data[11], data[12] = raw % 256, raw // 256
    data[13], data[14] = case % 256, case // 256
    data[15], data[16] = cabin % 256, cabin // 256
    return bytes(data)


# --- protocol layer ------------------------------------------------------------------------


def test_vevor_status_is_read():
    session = hp.HeaterSession(MAC, 1234, "vevor")
    status = session.feed(aa55_status())
    assert status is not None and session.protocol_name == "AA55"
    assert status.running and status.phase == "running" and status.mode == "temperature"
    assert status.target_temperature == 22 and status.level == 5
    assert (
        status.voltage == 12.8
        and status.cabin_temperature == 19
        and status.heater_temperature == 120
    )
    assert status.error is None


def test_faults_are_named():
    status = hp.HeaterSession(MAC, 1234, "vevor").feed(aa55_status(on=False, step=0, error=2))
    assert status.error_code == 2 and status.error == "Lack of fuel"
    assert status.phase == "standby" and not status.running


def test_commands_carry_the_pin():
    session = hp.HeaterSession(MAC, 1234, "vevor")
    # AA 55, PIN 12 34, command 3 (power) on, checksum of bytes 2-6
    assert session.command(hp.CMD_POWER, 1) == bytes([0xAA, 0x55, 12, 34, 3, 1, 0, 50])
    assert session.status_request()[4] == hp.CMD_STATUS


def test_sunster_lock_asks_for_a_login():
    session = hp.HeaterSession(MAC, 1234, "vevor")
    assert session.feed(bytes([0xAA, 0x77] + [0] * 8)) is None
    assert len(session.pending) == 1  # the encrypted PIN handshake
    assert session.protocol_name is not None


def test_hcalory_newer_models_log_in_first():
    session = hp.HeaterSession(MAC, 1234, "hcalory2")
    first = session.start()
    assert len(first) == 1 and first[0][7:9] == bytes([0x0A, 0x0C])  # password dpID
    assert session.start() == []  # only once


def test_shared_fff0_layout_tries_both_families():
    session = hp.HeaterSession(MAC, 1234, "abba")
    assert session.alternate() and session.transport == "hcalory1"
    assert session.alternate() and session.transport == "abba"


def test_heaters_are_recognized():
    assert hp.looks_like_heater("Air Heater", {}, [])
    assert hp.looks_like_heater("BYD-1234", {}, [])
    assert hp.looks_like_heater(None, {65294: b"\x01\x02\x99"}, [])
    assert hp.looks_like_heater(None, {}, ["0000FFE0-0000-1000-8000-00805F9B34FB"])
    assert not hp.looks_like_heater("SmartShunt HQ123", {737: b"\x10"}, [])


def test_layouts():
    notify, write = {"notify"}, {"write-without-response"}
    vevor = {
        "0000ffe0-0000-1000-8000-00805f9b34fb": {
            "0000ffe1-0000-1000-8000-00805f9b34fb": notify | write
        }
    }
    assert hp.choose_layout(vevor).transport == "vevor"
    fff0 = {hp.FFF0_SERVICE: {hp.FFF1: notify, hp.FFF2: write}}
    assert hp.choose_layout(fff0).transport == "abba"
    assert hp.choose_layout(fff0, "Hcalory-HBU1S").transport == "hcalory1"
    mvp2 = {hp.HCALORY_MVP2_SERVICE: {hp.HCALORY_MVP2_NOTIFY: notify, hp.HCALORY_MVP2_WRITE: write}}
    assert hp.choose_layout(mvp2) == hp.Layout(
        "hcalory2", hp.HCALORY_MVP2_NOTIFY, hp.HCALORY_MVP2_WRITE
    )
    assert hp.choose_layout({"0000180f-0000-1000-8000-00805f9b34fb": {}}) is None


# --- the service, with the simulated heaters -------------------------------------------------


class Clock:
    def __init__(self) -> None:
        self.now = 1_800_000_000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def heater(client, ctx):
    clock = Clock()
    ctx.hardware.heaters._clock = clock
    nearby = client.get("/api/heaters/nearby").json()["heaters"]
    assert {h["name"] for h in nearby} == {"Air Heater", "Hcalory-HBU1S"}
    response = client.post("/api/heaters", json={"name": "Diesel", "mac": nearby[0]["mac"]})
    assert response.status_code == 201, response.text
    return response.json(), clock


def test_add_switch_and_cool_down(client, heater):
    added, clock = heater
    assert added["connected"] and added["status"]["phase"] == "standby"
    assert "pin" not in added  # the PIN stays on the van

    on = client.post(f"/api/heaters/{added['id']}/power", json={"on": True}).json()
    assert on["status"]["running"] and on["status"]["phase_name"] == "Self-test"
    clock.now += 60
    assert client.get("/api/heaters").json()["heaters"][0]["status"]["phase"] == "running"

    off = client.post(f"/api/heaters/{added['id']}/power", json={"on": False}).json()
    assert off["status"]["phase"] == "cooldown"  # never just power cut: it cools down
    clock.now += 60
    assert client.get("/api/heaters").json()["heaters"][0]["status"]["phase"] == "standby"


def test_temperature_and_level(client, heater):
    added, _ = heater
    url = f"/api/heaters/{added['id']}/settings"
    view = client.post(url, json={"mode": "temperature", "temperature": 23}).json()
    assert view["status"]["target_temperature"] == 23
    view = client.post(url, json={"mode": "level", "level": 7}).json()
    assert view["status"]["mode"] == "level" and view["status"]["level"] == 7
    assert client.post(url, json={"temperature": 40}).status_code == 422
    assert client.post(url, json={"level": 0}).status_code == 422


def test_setup_is_checked(client, heater):
    added, _ = heater
    assert client.post("/api/heaters", json={"name": "Again", "mac": MAC}).status_code == 409
    assert client.post("/api/heaters", json={"name": "Bad", "mac": "nope"}).status_code == 422
    assert (
        client.post("/api/heaters", json={"name": "", "mac": "C8:47:8C:40:50:60"}).status_code
        == 422
    )
    renamed = client.patch(f"/api/heaters/{added['id']}", json={"name": "Webasto-ish", "pin": 4321})
    assert renamed.json()["name"] == "Webasto-ish"
    assert client.delete(f"/api/heaters/{added['id']}").status_code == 200
    assert client.get("/api/heaters").json()["heaters"] == []
    assert client.post(f"/api/heaters/{added['id']}/power", json={"on": True}).status_code == 404


def test_unreachable_heater_says_so(client, ctx, heater):
    added, _ = heater
    ctx.hardware.heaters._state.clear()  # as if out of range
    response = client.post(f"/api/heaters/{added['id']}/power", json={"on": True})
    assert response.status_code == 503 and "heater" in response.json()["detail"]


def test_scenes_switch_the_heater(client, ctx, heater):
    added, _ = heater
    key = f"heater:{added['id']}"
    scene = client.post(
        "/api/scenes", json={"name": "Warm up", "icon": "flame", "actions": {key: "on"}}
    )
    assert scene.status_code == 201, scene.text
    assert (
        client.post(
            "/api/scenes", json={"name": "X", "icon": "star", "actions": {key: "auto"}}
        ).status_code
        == 422
    )
    result = client.post(f"/api/scenes/{scene.json()['id']}/run").json()
    assert result["applied"] == [key]
    assert ctx.heaters.is_on(added["id"]) is True
    assert client.get("/api/scenes").json()["scenes"][0]["active"] is True


def test_remote_dashboard_controls_the_heater(ctx, heater):
    added, _ = heater
    assert build_state(ctx)["heaters"]["heaters"][0]["name"] == "Diesel"
    apply_command(ctx, {"type": "heater_power", "target": added["id"], "payload": {"on": True}})
    assert ctx.heaters.is_on(added["id"]) is True
    apply_command(
        ctx, {"type": "heater_settings", "target": added["id"], "payload": {"temperature": 18}}
    )
    assert ctx.heaters.get(added["id"])["status"]["target_temperature"] == 18


def test_heater_faults_are_sent(ctx, heater, monkeypatch):
    added, clock = heater
    real = ctx.hardware.heaters.link

    def faulty(heater_id):
        link = real(heater_id)
        link.status.error_code, link.status.error = 192, "EC0 - Carbon monoxide alarm"
        return link

    monkeypatch.setattr(ctx.hardware.heaters, "link", faulty)
    ctx.alerts.check()
    sent = [n["title"] for n in ctx.notifications.recent(10)]
    assert "Diesel: carbon monoxide alarm" in sent


def test_no_bluetooth_means_no_heaters(client, ctx):
    ctx.heaters._backend = None
    assert client.get("/api/heaters").json() == {"heaters": [], "available": False}
    assert client.get("/api/heaters/nearby").json() == {"heaters": []}


def test_link_type():
    assert HeaterLink(False, None, "connecting", None).connected is False
