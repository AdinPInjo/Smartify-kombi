"""Push notifications to your phone: ntfy and Telegram.

Every message goes through the ``notifications`` table, which is also the
outbox. Without internet a message stays queued and is retried with a growing
delay; one that is still undelivered after ``MAX_AGE_SECONDS`` is dropped
(news about a cold van from yesterday is no use any more). A message that
arrives late says so.

Quiet hours hold back normal messages until the morning. Urgent ones (the van
is moving, freezing or overheating inside) always go through.

Settings live in the database (``notification_settings``) so they can be
changed from the dashboard. They stay on the Pi: the remote dashboard never
receives them, because they include the Telegram bot token.
"""

from __future__ import annotations

import json
import logging
import secrets
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from smartify.db import transaction
from smartify.errors import DeviceUnavailable, InvalidInput

log = logging.getLogger(__name__)

Priority = Literal["low", "default", "high", "urgent"]
Channel = Literal["ntfy", "telegram"]
CHANNELS: tuple[Channel, ...] = ("ntfy", "telegram")

MAX_AGE_SECONDS = 24 * 3600
LATE_AFTER_SECONDS = 10 * 60
_MAX_RETRY_DELAY = 15 * 60
_HISTORY_DAYS = 30
_CLOCK_PATTERN = r"^([01]\d|2[0-3]):[0-5]\d$"
_TELEGRAM_API = "https://api.telegram.org"


# --- settings ---------------------------------------------------------------------


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NtfyChannel(_Model):
    enabled: bool = False
    server: str = Field(default="https://ntfy.sh", pattern=r"^https?://[^\s/]+(/[^\s]*)?$")
    topic: str = Field(default="", pattern=r"^[-_A-Za-z0-9]{0,64}$")
    """Anyone who knows the topic can read the messages, so it is long and random."""
    token: str = Field(default="", max_length=200, repr=False)
    """Access token, only for a protected (self-hosted) ntfy server."""

    @field_validator("server")
    @classmethod
    def _strip_slash(cls, value: str) -> str:
        return value.rstrip("/")


class TelegramChannel(_Model):
    enabled: bool = False
    bot_token: str = Field(default="", pattern=r"^(\d+:[A-Za-z0-9_-]{20,})?$", repr=False)
    chat_id: str = Field(default="", pattern=r"^-?\d{0,20}$")


class Channels(_Model):
    ntfy: NtfyChannel = Field(default_factory=NtfyChannel)
    telegram: TelegramChannel = Field(default_factory=TelegramChannel)


class SimpleAlert(_Model):
    enabled: bool = True


class ThresholdAlert(_Model):
    enabled: bool = True
    threshold: float


class SensorAlert(ThresholdAlert):
    sensor: str = Field(default="", max_length=32)
    """Climate sensor to watch. Empty = the first configured sensor."""


class DepartureAlert(_Model):
    """Anti-theft: the van drives off after standing still for a while."""

    enabled: bool = True
    after_minutes: int = Field(default=30, ge=5, le=24 * 60)
    """Only when the van stood still at least this long (not after a short stop)."""
    night_only: bool = False
    night_from: str = Field(default="22:00", pattern=_CLOCK_PATTERN)
    night_to: str = Field(default="07:00", pattern=_CLOCK_PATTERN)
    paused_until: int | None = None
    """Set by "I'm driving": no departure alerts until then."""


class EnergyForecastAlert(ThresholdAlert):
    battery_capacity_ah: float | None = Field(default=None, gt=0, le=5000)
    """Empty = estimated from the SmartShunt (consumed Ah and state of charge)."""
    solar_peak_w: float | None = Field(default=None, ge=0, le=10000)
    """Empty = the highest solar power seen in the last days."""


class QuietHours(_Model):
    enabled: bool = True
    from_: str = Field(default="22:00", alias="from", pattern=_CLOCK_PATTERN)
    to: str = Field(default="07:00", pattern=_CLOCK_PATTERN)

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class Alerts(_Model):
    battery_low: ThresholdAlert = Field(default_factory=lambda: ThresholdAlert(threshold=20))
    battery_not_charging: SimpleAlert = Field(default_factory=SimpleAlert)
    cold_inside: SensorAlert = Field(default_factory=lambda: SensorAlert(threshold=3))
    hot_inside: SensorAlert = Field(
        default_factory=lambda: SensorAlert(enabled=False, threshold=35)
    )
    water_low: ThresholdAlert = Field(default_factory=lambda: ThresholdAlert(threshold=10))
    sensor_fault: SimpleAlert = Field(default_factory=SimpleAlert)
    relay_cutoff: SimpleAlert = Field(default_factory=SimpleAlert)
    departure: DepartureAlert = Field(default_factory=DepartureAlert)
    frost_forecast: ThresholdAlert = Field(default_factory=lambda: ThresholdAlert(threshold=0))
    energy_forecast: EnergyForecastAlert = Field(
        default_factory=lambda: EnergyForecastAlert(threshold=20)
    )


class NotificationSettings(_Model):
    channels: Channels = Field(default_factory=Channels)
    alerts: Alerts = Field(default_factory=Alerts)
    quiet_hours: QuietHours = Field(default_factory=QuietHours)
    repeat_hours: int = Field(default=0, ge=0, le=48)
    """Remind again while an alert stays active. 0 = only once."""


def _deep_merge(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _readable(error: ValidationError) -> str:
    parts = []
    for item in error.errors():
        location = ".".join(str(p) for p in item["loc"])
        message = item["msg"].removeprefix("Value error, ")
        parts.append(f"{location}: {message}" if location else message)
    return "; ".join(parts)


def _dump(settings: NotificationSettings) -> dict[str, Any]:
    return settings.model_dump(mode="json", by_alias=True)


_TOPIC_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"  # no 0/o, 1/l/i: easy to type


def new_topic() -> str:
    """A random ntfy topic like ``kombi-k7m2-q9xr-4tnp-wd3h``.

    16 random characters (about 78 bits) are impossible to guess, and the
    groups make it easy to type into the phone app.
    """
    chars = "".join(secrets.choice(_TOPIC_ALPHABET) for _ in range(16))
    return "kombi-" + "-".join(chars[i : i + 4] for i in range(0, 16, 4))


def _clock_minutes(value: str) -> int:
    hours, minutes = value.split(":")
    return int(hours) * 60 + int(minutes)


def in_window(now: datetime, start: str, end: str) -> bool:
    """Is ``now`` inside the daily window ``start``-``end`` (may cross midnight)?"""
    minute = now.hour * 60 + now.minute
    a, b = _clock_minutes(start), _clock_minutes(end)
    if a == b:
        return False
    return a <= minute < b if a < b else minute >= a or minute < b


def window_end(now: datetime, end: str) -> datetime:
    """The next time the clock shows ``end`` (today or tomorrow)."""
    hours, minutes = (int(p) for p in end.split(":"))
    candidate = now.replace(hour=hours, minute=minutes, second=0, microsecond=0)
    return candidate if candidate > now else candidate + timedelta(days=1)


def _ago(seconds: float) -> str:
    minutes = int(seconds // 60)
    if minutes < 60:
        return f"{minutes} min"
    hours, rest = divmod(minutes, 60)
    return f"{hours} h {rest} min" if rest else f"{hours} h"


# --- transport ----------------------------------------------------------------------

Transport = Callable[[str, str, dict[str, str], bytes | None], tuple[int, bytes]]
"""``(method, url, headers, body) -> (status, response body)``"""


def http_request(
    method: str, url: str, headers: dict[str, str], body: bytes | None
) -> tuple[int, bytes]:
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    request.add_header("User-Agent", "smartify-kombi")
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


class SendError(Exception):
    """A channel could not deliver the message (no internet, wrong token...)."""


_NTFY_PRIORITY = {"low": 2, "default": 3, "high": 4, "urgent": 5}
_NTFY_TAGS = {"low": [], "default": ["van"], "high": ["warning"], "urgent": ["rotating_light"]}


def send_ntfy(
    config: NtfyChannel, message: dict[str, Any], transport: Transport = http_request
) -> None:
    if not config.topic:
        raise SendError("ntfy: no topic set")
    payload: dict[str, Any] = {
        "topic": config.topic,
        "title": message["title"],
        "message": message["message"],
        "priority": _NTFY_PRIORITY[message["priority"]],
        "tags": _NTFY_TAGS[message["priority"]],
    }
    if message.get("click_url"):
        payload["click"] = message["click_url"]
    headers = {"Content-Type": "application/json"}
    if config.token:
        headers["Authorization"] = f"Bearer {config.token}"
    # JSON publishing (POST to the server root) handles UTF-8 titles, unlike headers.
    try:
        status, body = transport("POST", config.server, headers, json.dumps(payload).encode())
    except (OSError, ValueError) as exc:
        raise SendError(f"ntfy: {_reason(exc)}") from None
    if status >= 300:
        raise SendError(f"ntfy: HTTP {status} {_snippet(body)}")


def _telegram_call(
    token: str, method: str, payload: dict[str, Any] | None, transport: Transport
) -> Any:
    url = f"{_TELEGRAM_API}/bot{token}/{method}"
    try:
        if payload is None:
            status, body = transport("GET", url, {}, None)
        else:
            data = json.dumps(payload).encode()
            status, body = transport("POST", url, {"Content-Type": "application/json"}, data)
    except (OSError, ValueError) as exc:
        # Never show the URL: it contains the bot token.
        raise SendError(f"Telegram: {_reason(exc).replace(token, '***')}") from None
    try:
        data = json.loads(body or b"{}")
    except ValueError:
        data = {}
    if status >= 300 or not data.get("ok"):
        description = data.get("description") or f"HTTP {status}"
        raise SendError(f"Telegram: {description}")
    return data.get("result")


def send_telegram(
    config: TelegramChannel, message: dict[str, Any], transport: Transport = http_request
) -> None:
    if not config.bot_token or not config.chat_id:
        raise SendError("Telegram: bot token or chat not set")
    text = f"{message['title']}\n{message['message']}"
    if message.get("click_url"):
        text += f"\n{message['click_url']}"
    _telegram_call(
        config.bot_token,
        "sendMessage",
        {
            "chat_id": config.chat_id,
            "text": text,
            "disable_web_page_preview": True,
            "disable_notification": message["priority"] == "low",
        },
        transport,
    )


def _reason(exc: BaseException) -> str:
    if isinstance(exc, urllib.error.URLError):
        return f"no connection ({exc.reason})"
    return str(exc) or type(exc).__name__


def _snippet(body: bytes) -> str:
    return body[:160].decode("utf-8", "replace").strip()


# --- service ----------------------------------------------------------------------------


class NotificationService:
    def __init__(
        self,
        db_path: Path,
        transport: Transport = http_request,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._db_path = db_path
        self._transport = transport
        self._clock = clock
        self._lock = threading.Lock()  # one delivery run at a time

    # --- settings ---------------------------------------------------------

    def settings(self) -> NotificationSettings:
        with transaction(self._db_path) as conn:
            row = conn.execute(
                "SELECT settings_json FROM notification_settings WHERE id = 1"
            ).fetchone()
        if row is None:
            settings = NotificationSettings()
            settings.channels.ntfy.topic = new_topic()
            self._save(settings)
            return settings
        stored = json.loads(row["settings_json"])
        try:
            # Merge over the defaults, so alerts added in an update get their defaults.
            return NotificationSettings.model_validate(
                _deep_merge(_dump(NotificationSettings()), stored)
            )
        except ValidationError:
            log.exception("Stored notification settings are invalid, using defaults")
            return NotificationSettings()

    def update_settings(self, patch: dict[str, Any]) -> NotificationSettings:
        merged = _deep_merge(_dump(self.settings()), patch)
        try:
            settings = NotificationSettings.model_validate(merged)
        except ValidationError as exc:
            raise InvalidInput(_readable(exc)) from None
        self._save(settings)
        return settings

    def _save(self, settings: NotificationSettings) -> None:
        with transaction(self._db_path) as conn:
            conn.execute(
                "INSERT INTO notification_settings (id, settings_json, updated_at) "
                "VALUES (1, ?, ?) "
                "ON CONFLICT (id) DO UPDATE SET settings_json = excluded.settings_json, "
                "updated_at = excluded.updated_at",
                (json.dumps(_dump(settings)), int(self._clock())),
            )

    def public_settings(self) -> dict[str, Any]:
        """Settings for the dashboard. The bot token is never sent back, only whether it is set."""
        data = _dump(self.settings())
        telegram = data["channels"]["telegram"]
        telegram["bot_token_set"] = bool(telegram["bot_token"])
        telegram["bot_token"] = ""
        ntfy = data["channels"]["ntfy"]
        ntfy["token_set"] = bool(ntfy["token"])
        ntfy["token"] = ""
        return data

    def active_channels(self, settings: NotificationSettings | None = None) -> list[Channel]:
        settings = settings or self.settings()
        channels: list[Channel] = []
        if settings.channels.ntfy.enabled and settings.channels.ntfy.topic:
            channels.append("ntfy")
        telegram = settings.channels.telegram
        if telegram.enabled and telegram.bot_token and telegram.chat_id:
            channels.append("telegram")
        return channels

    # --- sending ----------------------------------------------------------

    def notify(
        self,
        alert: str,
        title: str,
        message: str,
        priority: Priority = "default",
        click_url: str | None = None,
    ) -> int:
        """Queue a message. Urgent ones ignore quiet hours. Returns the notification id."""
        now = self._clock()
        settings = self.settings()
        next_attempt = now
        quiet = settings.quiet_hours
        local = datetime.fromtimestamp(now)
        if priority != "urgent" and quiet.enabled and in_window(local, quiet.from_, quiet.to):
            next_attempt = window_end(local, quiet.to).timestamp()
        with transaction(self._db_path) as conn:
            cursor = conn.execute(
                "INSERT INTO notifications (alert, title, message, priority, click_url, "
                "next_attempt_at, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (alert, title, message, priority, click_url, int(next_attempt), int(now)),
            )
            notification_id = int(cursor.lastrowid or 0)
        log.info("Notification queued: %s: %s", title, message)
        return notification_id

    def _send(self, channel: Channel, settings: NotificationSettings, message: dict) -> None:
        if channel == "ntfy":
            send_ntfy(settings.channels.ntfy, message, self._transport)
        else:
            send_telegram(settings.channels.telegram, message, self._transport)

    def deliver_due(self) -> None:
        """Send queued messages whose time has come. Called by the notify worker."""
        with self._lock:
            now = self._clock()
            with transaction(self._db_path) as conn:
                rows = conn.execute(
                    "SELECT * FROM notifications WHERE status = 'queued' AND next_attempt_at <= ? "
                    "ORDER BY id LIMIT 20",
                    (int(now),),
                ).fetchall()
            if not rows:
                return
            settings = self.settings()
            channels = self.active_channels(settings)
            for row in rows:
                self._deliver(row, settings, channels, now)

    def _deliver(
        self, row: Any, settings: NotificationSettings, channels: list[Channel], now: float
    ) -> None:
        age = now - row["created_at"]
        if age > MAX_AGE_SECONDS:
            self._finish(row["id"], "dropped", row["last_error"] or "too old to send")
            return
        if not channels:
            self._finish(row["id"], "dropped", "no notification channel set up")
            return
        delivered = set(json.loads(row["delivered_json"]))
        message = {
            "title": row["title"],
            "message": row["message"],
            "priority": row["priority"],
            "click_url": row["click_url"],
        }
        if age > LATE_AFTER_SECONDS:
            message["message"] += f"\n(Sent {_ago(age)} late: the van had no internet.)"
        errors = []
        for channel in channels:
            if channel in delivered:
                continue
            try:
                self._send(channel, settings, message)
                delivered.add(channel)
            except SendError as exc:
                errors.append(str(exc))
        with transaction(self._db_path) as conn:
            if not errors:
                conn.execute(
                    "UPDATE notifications SET status = 'sent', sent_at = ?, delivered_json = ?, "
                    "last_error = NULL WHERE id = ?",
                    (int(now), json.dumps(sorted(delivered)), row["id"]),
                )
                return
            attempts = row["attempts"] + 1
            delay = min(60 * 2 ** (attempts - 1), _MAX_RETRY_DELAY)
            conn.execute(
                "UPDATE notifications SET attempts = ?, next_attempt_at = ?, last_error = ?, "
                "delivered_json = ? WHERE id = ?",
                (
                    attempts,
                    int(now + delay),
                    "; ".join(errors),
                    json.dumps(sorted(delivered)),
                    row["id"],
                ),
            )
        if attempts == 1:
            log.info("Notification %d not sent yet: %s", row["id"], "; ".join(errors))

    def _finish(self, notification_id: int, status: str, error: str | None) -> None:
        with transaction(self._db_path) as conn:
            conn.execute(
                "UPDATE notifications SET status = ?, last_error = ? WHERE id = ?",
                (status, error, notification_id),
            )

    def send_test(self, channel: Channel) -> None:
        """Send a test message right away (not queued). Raises with a readable reason."""
        settings = self.settings()
        message = {
            "title": "Smartify test",
            "message": "Notifications from your van work. 🚐",
            "priority": "default",
            "click_url": None,
        }
        try:
            self._send(channel, settings, message)
        except SendError as exc:
            raise DeviceUnavailable(str(exc)) from None

    def detect_telegram_chat(self) -> dict[str, str]:
        """Find the chat of the last message sent to the bot and save it.

        The user sends any message (e.g. /start) to their bot first.
        """
        settings = self.settings()
        token = settings.channels.telegram.bot_token
        if not token:
            raise InvalidInput("save the bot token first")
        try:
            updates = _telegram_call(token, "getUpdates", None, self._transport) or []
        except SendError as exc:
            raise DeviceUnavailable(str(exc)) from None
        for update in reversed(updates):
            chat = (update.get("message") or update.get("my_chat_member") or {}).get("chat")
            if chat and "id" in chat:
                name = chat.get("title") or " ".join(
                    p for p in (chat.get("first_name"), chat.get("last_name")) if p
                )
                self.update_settings({"channels": {"telegram": {"chat_id": str(chat["id"])}}})
                return {"chat_id": str(chat["id"]), "name": name or chat.get("username") or ""}
        raise InvalidInput("no message found: send any message to your bot, then try again")

    # --- history & bookkeeping ---------------------------------------------------

    def recent(self, limit: int = 30) -> list[dict[str, Any]]:
        with transaction(self._db_path) as conn:
            rows = conn.execute(
                "SELECT id, alert, title, message, priority, status, last_error, attempts, "
                "created_at, sent_at, next_attempt_at FROM notifications ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def prune(self) -> None:
        cutoff = int(self._clock()) - _HISTORY_DAYS * 86400
        with transaction(self._db_path) as conn:
            conn.execute(
                "DELETE FROM notifications WHERE created_at < ? AND status != 'queued'", (cutoff,)
            )
