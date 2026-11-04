"""Updates from the dashboard: see what is new, install it, roll back.

Every release on GitHub carries ``versions.json`` (every version with its
changelog, made from CHANGELOG.md). The van reads the newest one a few times a
day. What happens then is the owner's choice (Settings → Updates):

* ``off``: nothing, not even a check.
* ``notify`` (default): a phone notification when a new version is out.
* ``auto``: the notification, and the van installs it at night (3:00-5:00)
  while parked.

Installing is done by ``deploy/updater.py`` in its own systemd unit, because
it restarts this service. The dashboard only writes ``update/request.json``
in the data folder; ``smartify-update.path`` starts the updater, which
reports its progress in ``update/status.json``. A version that does not start
is undone automatically.
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from smartify import __version__
from smartify.config import Settings
from smartify.db import transaction
from smartify.errors import Conflict, InvalidInput
from smartify.services.notify import NotificationService

log = logging.getLogger(__name__)

Mode = Literal["off", "notify", "auto"]
MODES = ("off", "notify", "auto")
MIN_VERSION = "0.4.0"
"""The first version with this updater. Going back further would lose the update button."""
AUTO_HOURS = (3, 5)
VERSION = re.compile(r"^\d+\.\d+\.\d+$")
REPO_DIR = Path(__file__).resolve().parents[3]
STALE_WAITING = 120  # seconds an install may wait for the updater to start
STALE_RUNNING = 3600  # an update running longer than this has died

Fetch = Callable[[str], Any]
Git = Callable[..., subprocess.CompletedProcess]


def key(version: str | None) -> tuple[int, ...]:
    if not version or not VERSION.match(version):
        return (0,)
    return tuple(int(part) for part in version.split("."))


def fetch_json(url: str) -> Any:
    request = urllib.request.Request(url, headers={"User-Agent": f"smartify-kombi/{__version__}"})
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return json.loads(response.read(1_000_000))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise UpdateCheckError("no release with update information yet") from None
        raise UpdateCheckError(f"GitHub answered HTTP {exc.code}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise UpdateCheckError(f"no connection to GitHub ({getattr(exc, 'reason', exc)})") from None
    except ValueError:
        raise UpdateCheckError("the update information is not valid") from None


def run_git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, timeout=10, check=False
    )


class UpdateCheckError(RuntimeError):
    pass


@dataclass(frozen=True)
class Availability:
    ok: bool
    reason: str | None = None


def short_notes(notes: str, items: int = 2) -> str:
    bullets = [line[2:].strip() for line in notes.splitlines() if line.startswith("- ")]
    text = "; ".join(bullets[:items])
    return text if len(text) <= 220 else text[:217] + "…"


class UpdateService:
    def __init__(
        self,
        settings: Settings,
        notifications: NotificationService,
        *,
        fetch: Fetch = fetch_json,
        git: Git = run_git,
        repo_dir: Path = REPO_DIR,
        clock: Callable[[], float] = time.time,
        moving: Callable[[], bool] = lambda: False,
        remote_version: Callable[[], str | None] = lambda: None,
        current: str = __version__,
    ) -> None:
        self._settings = settings
        self._db = settings.db_path
        self._notify = notifications
        self._fetch = fetch
        self._git = git
        self._repo = repo_dir
        self._clock = clock
        self._moving = moving
        self._remote_version = remote_version
        self.current = current
        self.folder = settings.data_dir / "update"
        self._availability: tuple[float, Availability] | None = None

    # --- stored state ------------------------------------------------------------------

    def _row(self) -> dict[str, Any]:
        with transaction(self._db) as conn:
            row = conn.execute("SELECT * FROM update_settings WHERE id = 1").fetchone()
        return dict(row)

    def _save(self, **values: Any) -> None:
        columns = ", ".join(f"{name} = ?" for name in values)
        with transaction(self._db) as conn:
            conn.execute(
                f"UPDATE update_settings SET {columns} WHERE id = 1", tuple(values.values())
            )

    @property
    def mode(self) -> Mode:
        return self._row()["mode"]

    def set_mode(self, mode: str) -> None:
        if mode not in MODES:
            raise InvalidInput("mode must be off, notify or auto")
        self._save(mode=mode)

    def versions(self) -> list[dict[str, Any]]:
        """Installable versions (0.4.0 and newer), newest first."""
        raw = self._row()["versions"]
        try:
            entries = json.loads(raw)["versions"] if raw else []
        except (ValueError, KeyError, TypeError):
            entries = []
        found = {}
        for entry in entries if isinstance(entries, list) else []:
            if not isinstance(entry, dict):
                continue
            version = str(entry.get("version", ""))
            if VERSION.match(version) and key(version) >= key(MIN_VERSION):
                found[version] = {
                    "version": version,
                    "date": entry.get("date") if isinstance(entry.get("date"), str) else None,
                    "notes": str(entry.get("notes") or "")[:20_000],
                }
        return sorted(found.values(), key=lambda e: key(e["version"]), reverse=True)

    def latest(self) -> str | None:
        versions = self.versions()
        return versions[0]["version"] if versions else None

    def update_available(self) -> bool:
        return key(self.latest()) > key(self.current)

    # --- checking ------------------------------------------------------------------------

    @property
    def versions_url(self) -> str:
        return f"https://github.com/{self._settings.update_repo}/releases/latest/download/versions.json"

    def check(self, force: bool = False) -> None:
        row = self._row()
        if not force and row["mode"] == "off":
            return
        due = (row["checked_at"] or 0) + self._settings.update_check_hours * 3600
        if not force and self._clock() < due:
            return
        try:
            data = self._fetch(self.versions_url)
            if not isinstance(data, dict) or not isinstance(data.get("versions"), list):
                raise UpdateCheckError("the update information is not valid")
        except UpdateCheckError as exc:
            log.info("Update check: %s", exc)
            self._save(checked_at=int(self._clock()), check_error=str(exc))
            return
        self._save(checked_at=int(self._clock()), check_error=None, versions=json.dumps(data))

    # --- installing ----------------------------------------------------------------------

    def availability(self) -> Availability:
        """Can this van install updates by itself? Cached for a minute (it runs git)."""
        now = self._clock()
        if self._availability and now - self._availability[0] < 60:
            return self._availability[1]
        result = self._find_availability()
        self._availability = (now, result)
        return result

    def _find_availability(self) -> Availability:
        if not Path(self._settings.updater_unit).exists():
            if self._settings.hardware != "pi":
                return Availability(False, "Updates are installed on the Raspberry Pi only.")
            return Availability(
                False,
                "To install updates from here, run the installer once more on the Pi: "
                "cd ~/smartify-kombi && sudo ./deploy/install.sh",
            )
        if not (self._repo / ".git").exists():
            return Availability(
                False, "This copy was not installed with git, so it can't update itself."
            )
        changes = self._git(self._repo, "status", "--porcelain", "--untracked-files=no")
        if changes.returncode != 0:
            return Availability(False, "git does not work in the Smartify folder.")
        if changes.stdout.strip():
            return Availability(
                False, "This copy has local code changes (a developer copy). Update it with git."
            )
        on_release = self._git(
            self._repo, "describe", "--tags", "--exact-match", "--match", "v*", "HEAD"
        )
        if on_release.returncode != 0:
            newer = self._git(self._repo, "tag", "--contains", "HEAD", "--list", "v*")
            if not newer.stdout.strip():
                return Availability(
                    False,
                    "This copy is ahead of the newest release (a developer copy). "
                    "Update it with git.",
                )
        return Availability(True)

    def status(self) -> dict[str, Any] | None:
        try:
            status = json.loads((self.folder / "status.json").read_text("utf-8"))
        except (OSError, ValueError):
            return None
        if not isinstance(status, dict):
            return None
        if status.get("state") == "running":
            age = self._clock() - float(status.get("started_at") or 0)
            waiting = status.get("step") == "Waiting for the updater"
            if waiting and age > STALE_WAITING:
                status.update(
                    state="failed",
                    message="The updater did not start. Run the installer once more on the Pi: "
                    "cd ~/smartify-kombi && sudo ./deploy/install.sh",
                )
            elif age > STALE_RUNNING:
                status.update(state="failed", message="The update stopped without finishing.")
        return status

    def history(self) -> list[dict[str, Any]]:
        try:
            history = json.loads((self.folder / "history.json").read_text("utf-8"))
        except (OSError, ValueError):
            return []
        return history if isinstance(history, list) else []

    def running(self) -> bool:
        status = self.status()
        return bool(status and status.get("state") == "running")

    def install(self, version: str, by: str = "dashboard") -> None:
        available = self.availability()
        if not available.ok:
            raise Conflict(available.reason or "updates can't be installed here")
        if self.running():
            raise Conflict("an update is already running")
        if version == self.current:
            raise InvalidInput(f"version {version} is already installed")
        if version not in {entry["version"] for entry in self.versions()}:
            raise InvalidInput(f"version {version} is not available (check for updates first)")
        frontend = self._settings.frontend_dir
        request = {
            "version": version,
            "by": by,
            "requested_at": int(self._clock()),
            "db_path": str(self._db.resolve()),
            "frontend_dir": str(frontend.resolve()) if frontend else None,
            "health_url": f"http://127.0.0.1:{self._settings.port}/api/health",
            "download_base": f"https://github.com/{self._settings.update_repo}/releases/download",
            # Public https, no key: works whatever "origin" is (an SSH deploy key may expire).
            "repo_url": f"https://github.com/{self._settings.update_repo}.git",
        }
        self.folder.mkdir(parents=True, exist_ok=True)
        status = {
            "state": "running",
            "target": version,
            "from": self.current,
            "by": by,
            "step": "Waiting for the updater",
            "message": None,
            "started_at": int(self._clock()),
            "finished_at": None,
            "log": [],
        }
        _write_json(self.folder / "status.json", status)
        # Written last and renamed into place: smartify-update.path starts on it.
        _write_json(self.folder / "request.json", request)
        log.info("Update to %s requested (%s)", version, by)

    # --- the worker ------------------------------------------------------------------------

    def tick(self) -> None:
        self.check()
        self._report_result()
        mode = self.mode
        if mode == "off":
            return
        self._announce(mode)
        if mode == "auto":
            self._install_at_night()

    def _announce(self, mode: Mode) -> None:
        latest = self.latest()
        row = self._row()
        if not self.update_available() or key(row["notified_version"]) >= key(latest):
            return
        entry = self.versions()[0]
        parts = []
        if short_notes(entry["notes"]):
            parts.append(f"New: {short_notes(entry['notes'])}.")
        if mode == "auto":
            parts.append("It installs by itself tonight, between 3 and 5, while the van is parked.")
        else:
            parts.append("Install it in Settings → Updates.")
        remote = self._remote_version()
        if remote and key(remote) < key(latest):
            parts.append("Your remote dashboard can be updated too, in its Settings.")
        self._notify.notify("update", f"Smartify {latest} is available", " ".join(parts))
        self._save(notified_version=latest)

    def _install_at_night(self) -> None:
        latest = self.latest()
        if not latest or not self.update_available():
            return
        hour = datetime.fromtimestamp(self._clock()).hour
        if not AUTO_HOURS[0] <= hour < AUTO_HOURS[1] or self._moving():
            return
        if self._row()["auto_version"] == latest or self.running() or not self.availability().ok:
            return
        self._save(auto_version=latest)  # one try per version: a failed one waits for you
        try:
            self.install(latest, by="automatic")
        except (Conflict, InvalidInput) as exc:
            log.warning("Automatic update to %s not started: %s", latest, exc)

    def _report_result(self) -> None:
        """Tell the owner how an automatic update went, and about any failed one."""
        status = self.status()
        if not status or status.get("state") == "running":
            return
        finished = int(status.get("finished_at") or 0)
        if finished <= (self._row()["reported_at"] or 0):
            return
        self._save(reported_at=finished)
        state = status.get("state")
        if state == "done" and status.get("by") == "automatic":
            self._notify.notify(
                "update", f"Smartify updated to {status.get('target')}", status.get("message") or ""
            )
        elif state in ("failed", "rolled_back"):
            self._notify.notify(
                "update",
                f"Update to {status.get('target')} did not work",
                status.get("message") or "",
                "high",
            )

    # --- for the dashboard ---------------------------------------------------------------

    def view(self) -> dict[str, Any]:
        row = self._row()
        available = self.availability()
        latest = self.latest()
        remote = self._remote_version()
        return {
            "current": self.current,
            "mode": row["mode"],
            "checked_at": row["checked_at"],
            "check_error": row["check_error"],
            "latest": latest,
            "update_available": self.update_available(),
            "versions": self.versions(),
            "can_install": available.ok,
            "reason": available.reason,
            "status": self.status(),
            "history": self.history()[:10],
            "remote": None
            if remote is None
            else {
                "version": remote,
                "update_available": key(latest) > key(remote) and key(remote) > (0,),
            },
            "auto_hours": list(AUTO_HOURS),
        }


def _write_json(path: Path, data: object) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data), "utf-8")
    os.replace(tmp, path)
