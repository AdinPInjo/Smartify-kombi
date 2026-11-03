"""The dashboard login.

Where the login comes from, in this order:

1. **dashboard**: created in the first-run setup (or changed under Settings),
   stored in the database with the password hashed (scrypt).
2. **env**: ``SMARTIFY_USERNAME`` / ``SMARTIFY_PASSWORD`` in ``.env``, for
   installs from before the setup screen and for scripted installs. The
   default ``changeme`` only counts with simulated hardware (development).
3. **setup**: neither: the dashboard shows the first-run setup, where whoever
   opens it first creates the login. Until then every API call except the
   setup itself is refused, and all relays stay off.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Literal

from smartify.config import DEFAULT_PASSWORD, Settings
from smartify.db import transaction
from smartify.errors import Conflict, InvalidInput

Source = Literal["dashboard", "env", "setup"]

_SCRYPT = {"n": 2**14, "r": 8, "p": 1}  # ~16 MB and well under a second on a Pi 3
_MIN_LENGTH = 8
_MAX_LENGTH = 128
_TOO_COMMON = {"changeme", "password", "12345678", "123456789", "qwertyui", "smartify", "kombi123"}


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, dklen=32, **_SCRYPT)
    return f"scrypt${_SCRYPT['n']}${_SCRYPT['r']}${_SCRYPT['p']}${salt.hex()}${digest.hex()}"


def check_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt, digest = stored.split("$")
    except ValueError:
        return False
    if scheme != "scrypt":
        return False
    candidate = hashlib.scrypt(
        password.encode(), salt=bytes.fromhex(salt), n=int(n), r=int(r), p=int(p), dklen=32
    )
    return hmac.compare_digest(candidate.hex(), digest)


def validate_username(username: str) -> str:
    username = username.strip()
    if not 1 <= len(username) <= 32 or any(c.isspace() for c in username):
        raise InvalidInput("the username needs 1 to 32 characters, without spaces")
    return username


def validate_password(password: str) -> None:
    if len(password) < _MIN_LENGTH:
        raise InvalidInput(f"the password needs at least {_MIN_LENGTH} characters")
    if len(password) > _MAX_LENGTH:
        raise InvalidInput(f"the password can have at most {_MAX_LENGTH} characters")
    if password.lower() in _TOO_COMMON:
        raise InvalidInput("that password is too easy to guess, pick another one")


class AccountService:
    def __init__(
        self,
        settings: Settings,
        db_path: Path,
        secret_key: str,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._settings = settings
        self._db_path = db_path
        self._secret = secret_key.encode()
        self._clock = clock
        self._lock = threading.Lock()  # setup must not run twice at once
        self._cache: tuple | None = None  # (row,) once read; every request checks the login

    def _row(self):
        if self._cache is None:
            with transaction(self._db_path) as conn:
                row = conn.execute("SELECT * FROM account WHERE id = 1").fetchone()
            self._cache = (dict(row) if row is not None else None,)
        return self._cache[0]

    def _env_password(self) -> str | None:
        password = self._settings.password
        if not password:
            return None
        if password == DEFAULT_PASSWORD and self._settings.hardware != "mock":
            return None  # the default never protects a real van
        return password

    @property
    def source(self) -> Source:
        if self._row() is not None:
            return "dashboard"
        return "env" if self._env_password() is not None else "setup"

    @property
    def setup_required(self) -> bool:
        return self.source == "setup"

    @property
    def uses_default_password(self) -> bool:
        return self.source == "env" and self._settings.password == DEFAULT_PASSWORD

    def username(self) -> str | None:
        row = self._row()
        if row is not None:
            return row["username"]
        return self._settings.username if self._env_password() is not None else None

    def verify(self, username: str, password: str) -> bool:
        """Constant-time check of a login attempt."""
        row = self._row()
        if row is not None:
            name_ok = hmac.compare_digest(username.encode(), row["username"].encode())
            return check_password(password, row["password_hash"]) and name_ok
        env_password = self._env_password()
        if env_password is None:
            return False
        name_ok = hmac.compare_digest(username.encode(), self._settings.username.encode())
        return hmac.compare_digest(password.encode(), env_password.encode()) and name_ok

    def fingerprint(self) -> str:
        """Kept in the session cookie: a new password signs every other device out."""
        row = self._row()
        material = row["password_hash"] if row is not None else (self._env_password() or "")
        return hmac.new(self._secret, material.encode(), hashlib.sha256).hexdigest()[:16]

    def _store(self, username: str, password: str) -> None:
        with transaction(self._db_path) as conn:
            conn.execute(
                "INSERT INTO account (id, username, password_hash, updated_at) VALUES (1, ?, ?, ?) "
                "ON CONFLICT (id) DO UPDATE SET username = excluded.username, "
                "password_hash = excluded.password_hash, updated_at = excluded.updated_at",
                (username, hash_password(password), int(self._clock())),
            )
        self._cache = None

    def create(self, username: str, password: str) -> str:
        """First-run setup. Only possible while no login exists."""
        username = validate_username(username)
        validate_password(password)
        with self._lock:
            if not self.setup_required:
                raise Conflict("the dashboard is already set up; sign in instead")
            self._store(username, password)
        return username

    def change(self, current_password: str, new_password: str, username: str | None = None) -> str:
        """New password, optionally a new username. An .env login moves to the database."""
        current_user = self.username()
        if current_user is None or not self.verify(current_user, current_password):
            raise InvalidInput("the current password is not right")
        new_username = validate_username(username) if username else current_user
        validate_password(new_password)
        with self._lock:
            self._store(new_username, new_password)
        return new_username
