"""Connecting the van to a remote dashboard from its own dashboard.

The remote dashboard's installer shows a *connection code*: ``SMK1-`` plus
base64url JSON ``{"u": url, "t": token}``. Pasting it (or following the
installer's "Connect my van" link) tests the connection once and stores it,
and syncing starts right away. A connection made here wins over
``SMARTIFY_CLOUD_URL`` / ``SMARTIFY_CLOUD_TOKEN`` in ``.env``.
"""

from __future__ import annotations

import base64
import binascii
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from smartify.db import transaction
from smartify.errors import InvalidInput

PREFIX = "SMK1-"
Source = Literal["dashboard", "env"]


@dataclass(frozen=True)
class Connection:
    url: str
    token: str
    source: Source


def parse_code(code: str) -> tuple[str, str]:
    """``SMK1-...`` -> (url, token). Raises InvalidInput with a readable reason."""
    code = re.sub(r"\s", "", code)
    if not code.startswith(PREFIX):
        raise InvalidInput("that is not a connection code: it starts with SMK1-")
    payload = code[len(PREFIX) :]
    try:
        data = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    except (binascii.Error, ValueError, UnicodeDecodeError):
        raise InvalidInput("the connection code is incomplete: copy all of it") from None
    url, token = (data.get("u"), data.get("t")) if isinstance(data, dict) else (None, None)
    if not isinstance(url, str) or not isinstance(token, str) or not token:
        raise InvalidInput("the connection code is incomplete: copy all of it")
    return check_url(url), token


def _local(host: str) -> bool:
    """A test setup on the local network (plain http is fine there)."""
    import ipaddress

    if host in ("localhost",) or host.endswith((".local", ".lan", ".test")):
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return address.is_private or address.is_loopback


def check_url(url: str) -> str:
    """Only https on the internet: the van's token and data must not travel unencrypted."""
    parsed = urlparse(url.strip())
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise InvalidInput("the remote dashboard address must start with https://")
    if parsed.scheme == "http" and not _local(parsed.hostname):
        raise InvalidInput(
            "the remote dashboard must use https:// (switch on the free SSL certificate in your "
            "hosting panel, then make a new connection code)"
        )
    return url.strip().rstrip("/")


class CloudConnectionStore:
    def __init__(self, db_path: Path, env_url: str, env_token: str) -> None:
        self._db_path = db_path
        self._env = (env_url.strip(), env_token.strip())

    def current(self) -> Connection | None:
        with transaction(self._db_path) as conn:
            row = conn.execute("SELECT url, token FROM cloud_connection WHERE id = 1").fetchone()
        if row is not None:
            return Connection(row["url"], row["token"], "dashboard")
        url, token = self._env
        return Connection(url, token, "env") if url and token else None

    def save(self, url: str, token: str) -> None:
        with transaction(self._db_path) as conn:
            conn.execute(
                "INSERT INTO cloud_connection (id, url, token, connected_at) VALUES (1, ?, ?, ?) "
                "ON CONFLICT (id) DO UPDATE SET url = excluded.url, token = excluded.token, "
                "connected_at = excluded.connected_at",
                (url, token, int(time.time())),
            )

    def clear(self) -> None:
        with transaction(self._db_path) as conn:
            conn.execute("DELETE FROM cloud_connection")
