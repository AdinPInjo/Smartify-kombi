"""Notifications, alerts, battery forecast, travel log and the new rule conditions."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from types import SimpleNamespace

import pytest

from smartify.db import migrate, transaction
from smartify.errors import InvalidInput
from smartify.hardware import GpsFix
from smartify.services import forecast
from smartify.services.alerts import AlertService
from smartify.services.conditions import evaluate, parse_condition
from smartify.services.gps import GpsState
from smartify.services.notify import NotificationService, in_window, window_end
from smartify.services.trips import TripService, nights, place_from


class Clock:
    def __init__(self, now: float) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def local_ts(year, month, day, hour, minute=0) -> float:
    return datetime(year, month, day, hour, minute).timestamp()


NOON = local_ts(2026, 11, 3, 12)


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "test.db"
    migrate(path)
    return path


class FakeTransport:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict, bytes | None]] = []
        self.fail = False
        self.responses: dict[str, tuple[int, bytes]] = {}

    def __call__(self, method, url, headers, body):
        if self.fail:
            raise OSError("network unreachable")
        self.calls.append((method, url, headers, body))
        for part, response in self.responses.items():
            if part in url:
                return response
        return 200, b'{"ok": true, "result": {}}'

    def payloads(self) -> list[dict]:
        return [json.loads(body) for _, _, _, body in self.calls if body]


def service(db, clock, transport=None, **channels) -> NotificationService:
    notify = NotificationService(db, transport or FakeTransport(), clock)
    notify.update_settings({"channels": channels, "quiet_hours": {"enabled": False}})
    return notify


# --- time windows and new rule conditions ------------------------------------------


def test_time_window_condition():
    morning = parse_condition({"type": "time", "from": "06:30", "to": "08:00"})
    assert evaluate(morning, lambda s, m: None, datetime(2026, 11, 3, 7, 0)).matched
    assert not evaluate(morning, lambda s, m: None, datetime(2026, 11, 3, 8, 0)).matched

    # Across midnight, weekdays only: Friday 23:00 and Saturday 02:00 belong to Friday night.
    night = parse_condition({"type": "time", "from": "22:00", "to": "07:00", "days": [4]})
    friday, saturday = datetime(2026, 11, 6, 23, 0), datetime(2026, 11, 7, 2, 0)
    assert evaluate(night, lambda s, m: None, friday).matched
    assert evaluate(night, lambda s, m: None, saturday).matched
    assert not evaluate(night, lambda s, m: None, datetime(2026, 11, 7, 23, 0)).matched


@pytest.mark.parametrize(
    "condition",
    [
        {"type": "time", "from": "25:00", "to": "07:00"},
        {"type": "time", "from": "07:00", "to": "07:00"},
        {"type": "time", "from": "07:00", "to": "08:00", "days": [7]},
        {"type": "threshold", "metric": "speed", "sensor": "gps", "op": ">", "value": 500},
    ],
)
def test_invalid_new_conditions(condition):
    with pytest.raises(InvalidInput):
        parse_condition(condition)


def test_rules_with_water_speed_and_schedule(client, ctx):
    relay = next(r for r in client.get("/api/relays").json()["relays"] if r["name"] == "fan")
    condition = {
        "type": "all",
        "conditions": [
            {"type": "threshold", "metric": "water_level", "sensor": "tank", "op": ">", "value": 5},
            {"type": "threshold", "metric": "speed", "sensor": "gps", "op": "<", "value": 3},
            {"type": "time", "from": "00:00", "to": "23:59"},
        ],
    }
    response = client.post(
        f"/api/relays/{relay['id']}/rules",
        json={"name": "x", "condition": condition, "action": "on"},
    )
    assert response.status_code == 201, response.text
    assert response.json()["condition"]["conditions"][2] == {
        "type": "time",
        "from": "00:00",
        "to": "23:59",
    }
    bad = {"type": "threshold", "metric": "water_level", "sensor": "grey", "op": ">", "value": 5}
    response = client.post(
        f"/api/relays/{relay['id']}/rules", json={"name": "y", "condition": bad, "action": "on"}
    )
    assert response.status_code == 422 and "tank" in response.json()["detail"]


def test_quiet_hours_window():
    assert in_window(datetime(2026, 1, 1, 23, 0), "22:00", "07:00")
    assert in_window(datetime(2026, 1, 1, 6, 59), "22:00", "07:00")
    assert not in_window(datetime(2026, 1, 1, 7, 0), "22:00", "07:00")
    assert window_end(datetime(2026, 1, 1, 23, 0), "07:00") == datetime(2026, 1, 2, 7, 0)


# --- settings ----------------------------------------------------------------------------


def test_settings_have_a_random_topic_and_merge_partial_updates(db):
    notify = NotificationService(db, FakeTransport(), Clock(NOON))
    topic = notify.settings().channels.ntfy.topic
    assert re.fullmatch(r"kombi(-[a-z2-9]{4}){4}", topic)
    assert NotificationService(db).settings().channels.ntfy.topic == topic  # stored

    notify.update_settings({"alerts": {"battery_low": {"threshold": 30}}})
    settings = notify.settings()
    assert settings.alerts.battery_low.threshold == 30
    assert settings.alerts.battery_low.enabled is True
    assert settings.alerts.water_low.threshold == 10

    with pytest.raises(InvalidInput):
        notify.update_settings({"alerts": {"departure": {"after_minutes": 1}}})
    with pytest.raises(InvalidInput):
        notify.update_settings({"channels": {"telegram": {"bot_token": "nonsense"}}})


def test_api_never_returns_tokens_and_empty_token_keeps_it(client):
    token = "123456:ABCdefGhIJKlmnoPQRstuVWxyz0123"
    response = client.patch(
        "/api/notifications/settings",
        json={"channels": {"telegram": {"enabled": True, "bot_token": token, "chat_id": "42"}}},
    )
    assert response.status_code == 200, response.text
    telegram = response.json()["channels"]["telegram"]
    assert telegram["bot_token"] == "" and telegram["bot_token_set"] is True
    assert response.json()["active_channels"] == ["telegram"]

    # The dashboard sends back what it got: an empty token must not erase the real one.
    client.patch(
        "/api/notifications/settings",
        json={"channels": {"telegram": {"bot_token": "", "bot_token_set": True}}},
    )
    ctx = client.app.state.ctx
    assert ctx.notifications.settings().channels.telegram.bot_token == token

    # null removes it
    response = client.patch(
        "/api/notifications/settings",
        json={"channels": {"telegram": {"enabled": False, "bot_token": None, "chat_id": ""}}},
    )
    assert response.json()["channels"]["telegram"]["bot_token_set"] is False
    assert ctx.notifications.settings().channels.telegram.bot_token == ""


# --- delivery --------------------------------------------------------------------------------


def test_ntfy_message_is_sent_as_json(db):
    transport = FakeTransport()
    notify = service(db, Clock(NOON), transport, ntfy={"enabled": True, "topic": "kombi-test"})
    notify.notify("battery_low", "Battery low", "Bateri ja 18 % ✓", "high", "https://osm.org/x")
    notify.deliver_due()
    method, url, _, _ = transport.calls[0]
    assert (method, url) == ("POST", "https://ntfy.sh")
    payload = transport.payloads()[0]
    assert payload["topic"] == "kombi-test" and payload["priority"] == 4
    assert payload["message"] == "Bateri ja 18 % ✓" and payload["click"] == "https://osm.org/x"
    assert notify.recent()[0]["status"] == "sent"


def test_telegram_message(db):
    transport = FakeTransport()
    token = "123456:ABCdefGhIJKlmnoPQRstuVWxyz0123"
    notify = service(
        db,
        Clock(NOON),
        transport,
        telegram={"enabled": True, "bot_token": token, "chat_id": "42"},
    )
    notify.notify("water_low", "Water tank almost empty", "Fresh water at 8 %.")
    notify.deliver_due()
    _, url, _, _ = transport.calls[0]
    assert url == f"https://api.telegram.org/bot{token}/sendMessage"
    payload = transport.payloads()[0]
    assert payload["chat_id"] == "42"
    assert payload["text"] == "Water tank almost empty\nFresh water at 8 %."


def test_offline_messages_wait_and_say_they_are_late(db):
    clock = Clock(NOON)
    transport = FakeTransport()
    notify = service(db, clock, transport, ntfy={"enabled": True, "topic": "kombi-test"})
    transport.fail = True
    notify.notify("cold_inside", "Cold in the van", "Inside is 2 °C.", "urgent")
    notify.deliver_due()
    row = notify.recent()[0]
    assert row["status"] == "queued" and "network unreachable" in row["last_error"]

    clock.now += 30  # retry not due yet
    transport.fail = False
    notify.deliver_due()
    assert transport.calls == []

    clock.now += 40 * 60
    notify.deliver_due()
    assert "Sent 40 min late" in transport.payloads()[0]["message"]
    assert notify.recent()[0]["status"] == "sent"


def test_two_channels_one_fails_no_duplicates(db):
    transport = FakeTransport()
    token = "123456:ABCdefGhIJKlmnoPQRstuVWxyz0123"
    transport.responses["telegram"] = (401, b'{"ok": false, "description": "Unauthorized"}')
    clock = Clock(NOON)
    notify = service(
        db,
        clock,
        transport,
        ntfy={"enabled": True, "topic": "kombi-test"},
        telegram={"enabled": True, "bot_token": token, "chat_id": "42"},
    )
    notify.notify("test", "T", "M")
    notify.deliver_due()
    assert notify.recent()[0]["last_error"] == "Telegram: Unauthorized"
    del transport.responses["telegram"]
    clock.now += 120
    notify.deliver_due()
    sent_to = [url for _, url, _, _ in transport.calls]
    assert sent_to.count("https://ntfy.sh") == 1  # not sent twice
    assert notify.recent()[0]["status"] == "sent"


def test_quiet_hours_hold_normal_messages_but_not_urgent(db):
    clock = Clock(local_ts(2026, 11, 3, 23, 30))
    transport = FakeTransport()
    notify = NotificationService(db, transport, clock)
    notify.update_settings({"channels": {"ntfy": {"enabled": True, "topic": "kombi-test"}}})
    notify.notify("water_low", "Water", "low")
    notify.notify("departure", "The van is moving!", "…", "urgent")
    notify.deliver_due()
    assert [p["title"] for p in transport.payloads()] == ["The van is moving!"]
    clock.now = local_ts(2026, 11, 4, 7, 1)
    notify.deliver_due()
    assert [p["title"] for p in transport.payloads()][-1] == "Water"


def test_no_channel_means_dropped(db):
    notify = NotificationService(db, FakeTransport(), Clock(NOON))
    notify.notify("test", "T", "M")
    notify.deliver_due()
    row = notify.recent()[0]
    assert row["status"] == "dropped" and "no notification channel" in row["last_error"]


def test_telegram_chat_detection(db):
    transport = FakeTransport()
    token = "123456:ABCdefGhIJKlmnoPQRstuVWxyz0123"
    updates = {"ok": True, "result": [{"message": {"chat": {"id": 987, "first_name": "Adin"}}}]}
    transport.responses["getUpdates"] = (200, json.dumps(updates).encode())
    notify = service(db, Clock(NOON), transport, telegram={"bot_token": token})
    assert notify.detect_telegram_chat() == {"chat_id": "987", "name": "Adin"}
    assert notify.settings().channels.telegram.chat_id == "987"


# --- alerts ---------------------------------------------------------------------------------


@dataclass
class FakeVan:
    soc: float | None = 80.0
    current: float | None = 1.0
    gps: GpsState = field(default_factory=lambda: GpsState("disabled", None, None, None))
    hourly: list = field(default_factory=list)

    def build(self):
        van = self
        return SimpleNamespace(
            energy=SimpleNamespace(
                summary=lambda: {
                    "available": van.soc is not None,
                    "battery": {"soc": van.soc, "current": van.current, "voltage": 12.8},
                },
                devices=lambda: [],
                history=lambda since: [],
            ),
            climate=SimpleNamespace(snapshots=lambda: []),
            water=SimpleNamespace(current=lambda: SimpleNamespace(ok=False, level_percent=None)),
            gps=SimpleNamespace(state=lambda: van.gps),
            relays=SimpleNamespace(tripped_ids=set(), list=lambda: []),
            weather=SimpleNamespace(hourly=lambda: van.hourly),
        )


def alerts_for(db, van: FakeVan, clock: Clock) -> tuple[AlertService, NotificationService]:
    notify = NotificationService(db, FakeTransport(), clock)
    return AlertService(van.build(), notify, db, clock), notify


def titles(notify: NotificationService) -> list[str]:
    return [row["title"] for row in reversed(notify.recent())]


def test_battery_low_needs_confirmation_and_hysteresis(db):
    clock, van = Clock(NOON), FakeVan(soc=19)
    alerts, notify = alerts_for(db, van, clock)
    alerts.check()
    assert titles(notify) == []  # one odd reading sends nothing
    clock.now += 130
    alerts.check()
    assert titles(notify) == ["Battery low"]

    van.soc = 22  # above 20 but within the hysteresis: still active, nothing new
    clock.now += 600
    alerts.check()
    van.soc = 26
    alerts.check()
    van.soc = 18
    alerts.check()
    clock.now += 130
    alerts.check()
    assert titles(notify) == ["Battery low", "Battery low"]


def test_active_alerts_are_not_sent_again_after_a_restart(db):
    clock, van = Clock(NOON), FakeVan(soc=15)
    alerts, notify = alerts_for(db, van, clock)
    alerts.check()
    clock.now += 130
    alerts.check()
    restarted, _ = alerts_for(db, van, clock)
    restarted.check()
    clock.now += 130
    restarted.check()
    assert titles(notify) == ["Battery low"]


def _parked(since: float, lat=44.0, lon=17.0) -> GpsState:
    return GpsState("ok", GpsFix(lat, lon, speed_kmh=0.0), int(since), None, True, int(since))


def _moving(now: float, lat=44.01, lon=17.0) -> GpsState:
    return GpsState("ok", GpsFix(lat, lon, speed_kmh=42.0), int(now), None, False, None)


def test_departure_alert_after_standing_still(db):
    clock, van = Clock(NOON), FakeVan(soc=None)
    alerts, notify = alerts_for(db, van, clock)
    van.gps = _parked(NOON - 10 * 60)  # 10 minutes: a short stop
    alerts.check()
    van.gps = _moving(clock.now)
    alerts.check()
    assert titles(notify) == []

    van.gps = _parked(clock.now - 3 * 3600)
    alerts.check()
    van.gps = _moving(clock.now)
    alerts.check()
    row = notify.recent()[0]
    assert row["title"] == "The van is moving!" and row["priority"] == "urgent"
    assert "3 h" in row["message"]
    with transaction(db) as conn:
        click = conn.execute("SELECT click_url FROM notifications").fetchone()[0]
    assert click.startswith("https://www.openstreetmap.org/?mlat=44.01000")


def test_departure_alert_can_be_paused(db):
    clock, van = Clock(NOON), FakeVan(soc=None)
    alerts, notify = alerts_for(db, van, clock)
    notify.update_settings({"alerts": {"departure": {"paused_until": int(NOON + 3600)}}})
    van.gps = _parked(NOON - 3 * 3600)
    alerts.check()
    van.gps = _moving(clock.now)
    alerts.check()
    assert titles(notify) == []


def test_frost_warning_once_per_evening(db):
    clock, van = Clock(local_ts(2026, 11, 3, 18)), FakeVan(soc=None)
    van.hourly = [
        {"ts": local_ts(2026, 11, 3, 22), "temperature_c": 1.0},
        {"ts": local_ts(2026, 11, 4, 5), "temperature_c": -6.2},
    ]
    alerts, notify = alerts_for(db, van, clock)
    alerts.check()
    clock.now += 3600
    alerts.check()
    rows = notify.recent()
    assert len(rows) == 1 and rows[0]["title"] == "Frost tonight"
    assert "-6 °C around 05:00" in rows[0]["message"]


# --- battery forecast ---------------------------------------------------------------------------


def _history(load_w: float, solar_w: float = 0.0, samples: int = 60) -> list[dict]:
    voltage = 12.8
    current = (solar_w - load_w) / voltage
    return [
        {"battery_voltage": voltage, "battery_current": current, "solar_power": solar_w}
        for _ in range(samples)
    ]


def test_forecast_without_sun_drains_by_the_load():
    summary = {"available": True, "battery": {"soc": 50.0, "voltage": 12.8, "consumed_ah": -50}}
    result = forecast.compute(summary, _history(load_w=64), [], NOON)
    assert result.available and result.capacity_ah == 100 and result.capacity_estimated
    assert result.load_w == pytest.approx(64)
    # 64 W of a 1280 Wh battery is 5 % per hour: 10 % after 8 hours.
    assert result.points[8]["soc"] == pytest.approx(10.0)
    assert result.low_at == result.points[8]["ts"]


def test_forecast_counts_tomorrows_sun():
    summary = {"available": True, "battery": {"soc": 50.0, "voltage": 12.8, "consumed_ah": -50}}
    history = _history(load_w=64) + _history(load_w=64, solar_w=200, samples=5)
    hour = int(NOON) // 3600
    sunny = [{"ts": (hour + i) * 3600, "radiation_w_m2": 800.0} for i in range(6)]
    result = forecast.compute(summary, history, sunny, NOON)
    assert result.solar_peak_w == 200
    assert result.points[6]["soc"] > 50  # gains while the sun shines


def test_forecast_needs_a_battery_monitor():
    assert not forecast.compute({"available": False}, [], [], NOON).available


# --- travel log ---------------------------------------------------------------------------------


class FakeGps:
    def __init__(self) -> None:
        self.current = GpsState("disabled", None, None, None)
        self.km = 0.0

    def state(self) -> GpsState:
        return self.current

    def total_distance_km(self) -> float:
        return self.km


def test_stops_are_logged_with_nights_and_km(db):
    clock, gps = Clock(local_ts(2026, 11, 3, 18)), FakeGps()
    names = iter([("Jajce", "Bosnia and Herzegovina"), ("Mostar", "Bosnia and Herzegovina")])
    trips = TripService(gps, db, geocoder=lambda lat, lon: next(names), clock=clock)

    gps.current = _parked(clock.now - 1800)  # 30 minutes: not a stop yet
    trips.tick()
    assert trips.stops() == []
    clock.now += 3600
    trips.tick()
    first = trips.stops()[0]
    assert first["place"] == "Jajce" and first["here_now"] and first["km_from_previous"] is None

    # Next morning: drive 120 km and stop again.
    clock.now = local_ts(2026, 11, 4, 9)
    for _ in range(3):
        gps.current = _moving(clock.now, lat=43.5)
        trips.tick()
        clock.now += 30
    gps.km = 120.0
    clock.now = local_ts(2026, 11, 4, 12)
    gps.current = _parked(clock.now - 2 * 3600, lat=43.34, lon=17.81)
    trips.tick()
    stops = trips.stops()
    assert [s["place"] for s in stops] == ["Mostar", "Jajce"]
    assert stops[1]["nights"] == 1 and not stops[1]["here_now"]
    assert stops[0]["km_from_previous"] == 120.0


def test_lost_gps_does_not_end_a_stop(db):
    clock, gps = Clock(NOON), FakeGps()
    trips = TripService(gps, db, geocoder=lambda lat, lon: ("X", None), clock=clock)
    gps.current = _parked(NOON - 2 * 3600)
    trips.tick()
    gps.current = GpsState("no_fix", None, None, None)
    for _ in range(10):
        clock.now += 30
        trips.tick()
    assert trips.stops()[0]["here_now"]


def test_nights_and_place_names():
    assert nights(local_ts(2026, 11, 3, 18), local_ts(2026, 11, 3, 23)) == 0
    assert nights(local_ts(2026, 11, 3, 18), local_ts(2026, 11, 6, 10)) == 3
    assert place_from({"address": {"town": "Jajce", "country": "BiH"}}) == ("Jajce", "BiH")
    assert place_from({"display_name": "Somewhere, Far", "address": {}}) == ("Somewhere", None)


def test_api_stops_and_forecast(client):
    assert client.get("/api/stops").json() == {"stops": []}
    assert "available" in client.get("/api/energy/forecast").json()
    assert client.get("/api/notifications").json() == {"notifications": []}


def test_stops_table_survives_in_db(db):
    with transaction(db) as conn:
        conn.execute("INSERT INTO stops (lat, lon, arrived_at) VALUES (1, 2, 3)")
        assert conn.execute("SELECT COUNT(*) FROM stops").fetchone()[0] == 1
