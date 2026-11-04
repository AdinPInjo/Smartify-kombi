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
import logging
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

log = logging.getLogger(__name__)

_SCRYPT = {"n": 2**14, "r": 8, "p": 1}  # ~16 MB and well under a second on a Pi 3
_MIN_LENGTH = 8
_MAX_LENGTH = 128
_TOO_COMMON = {"changeme", "password", "12345678", "123456789", "qwertyui", "smartify", "kombi123"}


# One password hash at a time: each takes ~16 MB, and parallel login attempts
# must not be able to use up a Pi's memory.
_HASHING = threading.BoundedSemaphore(1)

SETUP_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O, 1/I/L


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    with _HASHING:
        digest = hashlib.scrypt(password.encode(), salt=salt, dklen=32, **_SCRYPT)
    return f"scrypt${_SCRYPT['n']}${_SCRYPT['r']}${_SCRYPT['p']}${salt.hex()}${digest.hex()}"


def check_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt, digest = stored.split("$")
    except ValueError:
        return False
    if scheme != "scrypt":
        return False
    with _HASHING:
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


def new_setup_code() -> str:
    raw = "".join(secrets.choice(SETUP_CODE_ALPHABET) for _ in range(8))
    return f"{raw[:4]}-{raw[4:]}"


class TooManyAttempts(Exception):
    def __init__(self, wait_seconds: int) -> None:
        super().__init__(f"too many wrong attempts: try again in {max(1, wait_seconds // 60)} min")
        self.wait_seconds = wait_seconds


class LoginGuard:
    """Slows down password and setup-code guessing.

    After 5 wrong attempts from one address within 15 minutes, that address waits
    15 minutes; after 30 wrong attempts from anywhere, everyone does.
    """

    WINDOW = 15 * 60
    PER_ADDRESS = 5
    OVERALL = 30

    def __init__(self, clock: Callable[[], float] = time.time) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._failures: dict[str, list[float]] = {}

    def _recent(self, key: str, now: float) -> list[float]:
        times = [t for t in self._failures.get(key, []) if now - t < self.WINDOW]
        if times:
            self._failures[key] = times
        else:
            self._failures.pop(key, None)
        return times

    def check(self, address: str) -> None:
        now = self._clock()
        with self._lock:
            mine = self._recent(address, now)
            everyone = self._recent("*", now)
            if len(mine) >= self.PER_ADDRESS:
                raise TooManyAttempts(int(self.WINDOW - (now - mine[0])))
            if len(everyone) >= self.OVERALL:
                raise TooManyAttempts(int(self.WINDOW - (now - everyone[0])))

    def failed(self, address: str) -> None:
        now = self._clock()
        with self._lock:
            for key in (address, "*"):
                self._failures.setdefault(key, []).append(now)

    def succeeded(self, address: str) -> None:
        with self._lock:
            self._failures.pop(address, None)


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
        self.guard = LoginGuard(clock)
        self.setup_code_file = settings.data_dir / "setup-code.txt"

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

    # --- the setup code: only someone at the Pi can create the first login ---------

    def setup_code(self) -> str | None:
        """The current setup code, made (and logged) if there is none. None once set up."""
        if not self.setup_required:
            return None
        try:
            code = self.setup_code_file.read_text().strip()
            if len(code.replace("-", "")) == 8:
                return code
        except OSError:
            pass
        code = new_setup_code()
        self.setup_code_file.parent.mkdir(parents=True, exist_ok=True)
        self.setup_code_file.write_text(code + "\n")
        self.setup_code_file.chmod(0o600)
        log.warning("Dashboard setup code: %s (needed once, to create the login)", code)
        return code

    def check_setup_code(self, given: str) -> bool:
        code = self.setup_code()
        if code is None:
            return False
        normalize = lambda value: "".join(c for c in value.upper() if c.isalnum())  # noqa: E731
        return hmac.compare_digest(normalize(given).encode(), normalize(code).encode())

    def create(self, username: str, password: str, setup_code: str = "") -> str:
        """First-run setup: needs the setup code; only possible while no login exists."""
        username = validate_username(username)
        validate_password(password)
        with self._lock:
            if not self.setup_required:
                raise Conflict("the dashboard is already set up; sign in instead")
            if not self.check_setup_code(setup_code):
                raise InvalidInput("the setup code is not right")
            self._store(username, password)
        self.setup_code_file.unlink(missing_ok=True)
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
