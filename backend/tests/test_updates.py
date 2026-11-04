"""Settings → Updates: checking, notifying, automatic installs, and the updater itself."""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import sqlite3
import subprocess
import sys
import tarfile
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from smartify.config import Settings
from smartify.db import migrate, transaction
from smartify.errors import Conflict, InvalidInput
from smartify.services.notify import NotificationService
from smartify.services.updates import UpdateCheckError, UpdateService, short_notes

ROOT = Path(__file__).resolve().parents[2]

VERSIONS = {
    "schema": 1,
    "latest": "0.5.0",
    "versions": [
        {
            "version": "0.5.0",
            "date": "2026-12-01",
            "notes": "### Added\n- Coffee machine relay\n- Sunrise rule",
        },
        {"version": "0.4.1", "date": "2026-11-20", "notes": "### Fixed\n- Map tiles"},
        {"version": "0.4.0", "date": "2026-11-03", "notes": "### Added\n- Updates"},
        {"version": "0.3.1", "date": "2026-11-03", "notes": "too old for the updater"},
        {"version": "nonsense", "notes": "ignored"},
    ],
}


def ok_git(_repo, *args):
    """git as on a clean install sitting on a release tag."""
    return subprocess.CompletedProcess(
        args, 0, stdout="v0.4.0\n" if "describe" in args else "", stderr=""
    )


class Clock:
    def __init__(self, hour: int = 12) -> None:
        self.now = datetime(2026, 12, 2, hour, 30).timestamp()

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def make(tmp_path: Path):
    def build(
        *, current="0.4.0", hour=12, git=ok_git, fetch=None, moving=False, unit=True, remote=None
    ):
        unit_file = tmp_path / "smartify-update.path"
        if unit:
            unit_file.write_text("")
        settings = Settings(
            _env_file=None,
            hardware="pi",
            data_dir=tmp_path,
            password="x" * 10,
            secret_key="s",
            updater_unit=unit_file,
            frontend_dir=tmp_path / "dist",
        )
        migrate(settings.db_path)
        (tmp_path / ".git").mkdir(exist_ok=True)
        notifications = NotificationService(settings.db_path)
        clock = Clock(hour)
        service = UpdateService(
            settings,
            notifications,
            fetch=fetch or (lambda url: VERSIONS),
            git=git,
            repo_dir=tmp_path,
            clock=clock,
            moving=lambda: moving,
            remote_version=lambda: remote,
            current=current,
        )
        return service, notifications, clock

    return build


def sent(service: UpdateService) -> list[tuple[str, str]]:
    with transaction(service._db) as conn:
        return [
            (r["title"], r["message"])
            for r in conn.execute("SELECT title, message FROM notifications ORDER BY id")
        ]


def test_check_lists_installable_versions_newest_first(make):
    service, _, _ = make()
    service.check()
    assert [v["version"] for v in service.versions()] == ["0.5.0", "0.4.1", "0.4.0"]
    assert service.latest() == "0.5.0" and service.update_available()
    view = service.view()
    assert view["current"] == "0.4.0" and view["mode"] == "notify" and view["can_install"]


def test_check_respects_off_and_the_interval_and_keeps_old_data_on_errors(make):
    calls = []

    def fetch(url):
        calls.append(url)
        if len(calls) > 1:
            raise UpdateCheckError("no connection to GitHub (offline)")
        return VERSIONS

    service, _, clock = make(fetch=fetch)
    service.check()
    service.check()  # not due yet
    assert len(calls) == 1
    assert (
        calls[0]
        == "https://github.com/AdinPInjo/Smartify-kombi/releases/latest/download/versions.json"
    )
    clock.now += 7 * 3600
    service.check()
    view = service.view()
    assert view["check_error"] == "no connection to GitHub (offline)"
    assert view["latest"] == "0.5.0"  # what we knew stays
    service.set_mode("off")
    clock.now += 7 * 3600
    service.check()
    assert len(calls) == 2
    with pytest.raises(InvalidInput):
        service.set_mode("sometimes")


def test_notifies_once_per_version_and_mentions_the_remote_dashboard(make):
    service, _, _ = make(remote="0.4.0")
    service.tick()
    service.tick()
    [(title, message)] = sent(service)
    assert title == "Smartify 0.5.0 is available"
    assert "Coffee machine relay; Sunrise rule" in message
    assert "Settings → Updates" in message and "remote dashboard" in message


def test_automatic_installs_only_at_night_while_parked_and_tries_once(make):
    service, _, clock = make(hour=12)
    service.set_mode("auto")
    service.tick()
    assert not (service.folder / "request.json").exists()  # daytime

    service, _, clock = make(hour=3, moving=True)
    service.tick()
    assert not (service.folder / "request.json").exists()  # driving

    service, _, clock = make(hour=3)
    service.tick()
    request = json.loads((service.folder / "request.json").read_text())
    assert request["version"] == "0.5.0" and request["by"] == "automatic"
    assert (
        request["download_base"] == "https://github.com/AdinPInjo/Smartify-kombi/releases/download"
    )
    assert request["health_url"].endswith("/api/health")
    # The updater "fails": no second automatic try for the same version.
    (service.folder / "request.json").unlink()
    status = json.loads((service.folder / "status.json").read_text())
    status.update(state="rolled_back", finished_at=int(clock.now), message="went back")
    (service.folder / "status.json").write_text(json.dumps(status))
    service.tick()
    assert not (service.folder / "request.json").exists()
    assert sent(service)[-1] == ("Update to 0.5.0 did not work", "went back")


def test_install_checks_before_asking_the_updater(make):
    service, _, _ = make()
    service.check()
    with pytest.raises(InvalidInput):
        service.install("0.4.0")  # installed
    with pytest.raises(InvalidInput):
        service.install("0.3.1")  # too old: has no updater
    service.install("0.4.1")
    assert service.status()["state"] == "running"
    with pytest.raises(Conflict):
        service.install("0.5.0")  # already running


def test_waiting_for_an_updater_that_never_starts_is_reported(make):
    service, _, clock = make()
    service.check()
    service.install("0.5.0")
    clock.now += 200
    status = service.status()
    assert status["state"] == "failed" and "install.sh" in status["message"]


@pytest.mark.parametrize(
    ("unit", "git_out", "reason"),
    [
        (False, {}, "run the installer once more"),
        (True, {"status": " M backend/smartify/main.py"}, "local code changes"),
        (True, {"describe": None, "tag": ""}, "ahead of the newest release"),
    ],
)
def test_developer_copies_and_old_installs_cannot_update_themselves(make, unit, git_out, reason):
    def git(_repo, *args):
        out = git_out.get(args[0], "v0.4.0\n" if args[0] == "describe" else "")
        code = 1 if out is None else 0
        return subprocess.CompletedProcess(args, code, stdout=out or "", stderr="")

    service, _, _ = make(unit=unit, git=git)
    service.check()
    view = service.view()
    assert not view["can_install"] and reason in view["reason"]
    with pytest.raises(Conflict):
        service.install("0.5.0")


def test_behind_a_release_on_a_branch_can_update(make):
    def git(_repo, *args):
        if args[0] == "describe":
            return subprocess.CompletedProcess(args, 128, "", "no tag")
        return subprocess.CompletedProcess(args, 0, "v0.4.1\n" if args[0] == "tag" else "", "")

    service, _, _ = make(git=git)
    assert service.availability().ok


def test_short_notes():
    assert short_notes("### Added\n- One\n- Two\n- Three") == "One; Two"


def test_api(client, ctx, tmp_path):
    ctx.updates._fetch = lambda url: VERSIONS
    # As on a computer without the updater (the Pi running these tests may have it).
    ctx.updates._settings = ctx.settings.model_copy(update={"updater_unit": tmp_path / "none"})
    view = client.post("/api/updates/check").json()
    assert view["latest"] == "0.5.0" and view["current"] == ctx.updates.current
    assert not view["can_install"]  # tests run in mock mode, no updater unit
    assert client.patch("/api/updates/settings", json={"mode": "auto"}).json()["mode"] == "auto"
    assert client.patch("/api/updates/settings", json={"mode": "maybe"}).status_code == 422
    response = client.post("/api/updates/install", json={"version": "0.5.0"})
    assert response.status_code == 409 and "Raspberry Pi" in response.json()["detail"]


def test_release_info_reads_the_changelog():
    spec = importlib.util.spec_from_file_location("release_info", ROOT / "scripts/release_info.py")
    release_info = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(release_info)
    entries = release_info.parse_changelog(
        "# Changelog\n\n## Unreleased\n- soon\n\n"
        "## 0.4.1 - 2026-11-20\n### Fixed\n- Map\n\n"
        "## 0.4.0 - 2026-11-03\n- First\n"
    )
    assert entries == [
        {"version": "0.4.1", "date": "2026-11-20", "notes": "### Fixed\n- Map"},
        {"version": "0.4.0", "date": "2026-11-03", "notes": "- First"},
    ]
    from smartify import __version__

    assert release_info.check(__version__) == []  # this repo's changelog and versions agree


# --- deploy/updater.py, for real: git tags, downloads, restart, health, rollback ----------


def load_updater():
    spec = importlib.util.spec_from_file_location("smartify_updater", ROOT / "deploy/updater.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True
    ).stdout


def release(source: Path, files: Path, version: str, *, broken: bool = False) -> None:
    (source / "backend/smartify/__init__.py").write_text(f'__version__ = "{version}"\n')
    (source / "BROKEN").write_text("yes" if broken else "no")
    git(source, "add", "-A")
    git(source, "commit", "-q", "-m", version)
    git(source, "tag", f"v{version}")
    folder = files / f"v{version}"
    folder.mkdir(parents=True)
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        data = f"dashboard {version}".encode()
        info = tarfile.TarInfo("./index.html")
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
    (folder / "dashboard.tar.gz").write_bytes(buffer.getvalue())
    digest = hashlib.sha256(buffer.getvalue()).hexdigest()
    (folder / "SHA256SUMS").write_text(f"{digest}  dashboard.tar.gz\n")


@pytest.fixture
def van(tmp_path: Path):
    """A van checkout at v0.4.0 with an origin that has 0.4.1 and a broken 0.4.2."""
    source, origin, repo, files = (tmp_path / n for n in ("source", "origin.git", "van", "files"))
    (source / "backend/smartify").mkdir(parents=True)
    (source / "backend/pyproject.toml").write_text("[project]\nname='x'\n")
    git(tmp_path, "init", "-q", "-b", "main", str(source))
    git(source, "config", "user.email", "t@example.com")
    git(source, "config", "user.name", "t")
    release(source, files, "0.4.0")
    release(source, files, "0.4.1")
    release(source, files, "0.4.2", broken=True)
    git(tmp_path, "clone", "-q", "--bare", str(source), str(origin))
    git(tmp_path, "clone", "-q", str(origin), str(repo))
    git(repo, "-c", "advice.detachedHead=false", "checkout", "-q", "--detach", "v0.4.0")
    data = repo / "backend/data"
    (data / "update").mkdir(parents=True)
    db = data / "smartify.db"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE notes (text TEXT)")
        conn.execute("INSERT INTO notes VALUES ('before the update')")
    dist = repo / "frontend/dist"
    dist.mkdir(parents=True)
    (dist / "index.html").write_text("dashboard 0.4.0")

    # A pretend smartify.service: "running" serves /api/health with the checked-out
    # version; a broken version answers 500 (and has already written to the database).
    state = {"running": True}

    class Health(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            code = (repo / "backend/smartify/__init__.py").read_text().split('"')[1]
            if not state["running"] or (repo / "BROKEN").read_text() == "yes":
                self.send_response(500)
                self.end_headers()
                return
            body = json.dumps({"version": code}).encode()
            self.send_response(200)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Health)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    systemctl = tmp_path / "systemctl.py"
    systemctl.write_text(
        "import sqlite3, sys\n"
        f"open({str(tmp_path / 'service.log')!r}, 'a').write(sys.argv[1] + '\\n')\n"
        "if sys.argv[1] == 'restart':\n"
        f"    conn = sqlite3.connect({str(db)!r})\n"
        "    conn.execute(\"INSERT INTO notes VALUES ('new version ran')\")\n"
        "    conn.commit()\n"
    )

    def update(version: str, **extra) -> dict:
        request = {
            "version": version,
            "by": "dashboard",
            "db_path": str(db),
            "frontend_dir": str(dist),
            "health_url": f"http://127.0.0.1:{server.server_port}/api/health",
            "download_base": files.as_uri(),
            **extra,
        }
        (data / "update/request.json").write_text(json.dumps(request))
        load_updater().main(
            [
                "--data-dir",
                str(data),
                "--repo",
                str(repo),
                "--systemctl",
                f"{sys.executable} {systemctl}",
                "--health-timeout",
                "4",
            ]
        )
        assert not (data / "update/request.json").exists()
        return json.loads((data / "update/status.json").read_text())

    def notes() -> list[str]:
        with sqlite3.connect(db) as conn:
            return [row[0] for row in conn.execute("SELECT text FROM notes")]

    yield {
        "update": update,
        "origin": origin,
        "repo": repo,
        "dist": dist,
        "notes": notes,
        "data": data,
        "log": tmp_path / "service.log",
    }
    server.shutdown()


def test_updater_installs_a_release(van):
    status = van["update"]("0.4.1")
    assert status["state"] == "done", status
    assert status["from"] == "0.4.0" and status["target"] == "0.4.1"
    assert git(van["repo"], "describe", "--tags").strip() == "v0.4.1"
    assert (van["dist"] / "index.html").read_text() == "dashboard 0.4.1"
    assert not van["dist"].with_name("dist.previous").exists()
    assert van["notes"]() == ["before the update", "new version ran"]  # data kept
    backups = list((van["data"] / "backups").glob("before-update-0.4.0-to-0.4.1-*.db"))
    assert len(backups) == 1
    history = json.loads((van["data"] / "update/history.json").read_text())
    assert history[0]["state"] == "done"

    # Going back is the same: install the older version.
    assert van["update"]("0.4.0")["state"] == "done"
    assert (van["dist"] / "index.html").read_text() == "dashboard 0.4.0"


def test_updater_undoes_a_version_that_does_not_start(van):
    assert van["update"]("0.4.1")["state"] == "done"
    status = van["update"]("0.4.2")
    assert status["state"] == "rolled_back", status
    assert "went back to 0.4.1" in status["message"]
    assert git(van["repo"], "describe", "--tags").strip() == "v0.4.1"
    assert (van["dist"] / "index.html").read_text() == "dashboard 0.4.1"
    # The database is as it was right before the failed update.
    assert van["notes"]() == ["before the update", "new version ran"]
    assert van["log"].read_text().split() == ["restart", "restart", "stop", "start"]


def test_updater_changes_nothing_when_the_download_is_wrong(van, tmp_path):
    (tmp_path / "files/v0.4.1/SHA256SUMS").write_text("0" * 64 + "  dashboard.tar.gz\n")
    status = van["update"]("0.4.1")
    assert status["state"] == "failed" and "checksum" in status["message"]
    assert git(van["repo"], "describe", "--tags").strip() == "v0.4.0"
    assert (van["dist"] / "index.html").read_text() == "dashboard 0.4.0"
    assert not van["log"].exists()  # never restarted


def test_updater_refuses_local_changes(van):
    (van["repo"] / "backend/pyproject.toml").write_text("changed")
    status = van["update"]("0.4.1")
    assert status["state"] == "failed" and "local code changes" in status["message"]


def test_updater_fetches_from_the_public_address_not_origin(van):
    # Like a Pi whose SSH deploy key was removed on GitHub: "origin" can't be reached.
    git(van["repo"], "remote", "set-url", "origin", "git@github.invalid:nobody/nothing.git")
    status = van["update"]("0.4.1", repo_url=str(van["origin"]))
    assert status["state"] == "done", status
    assert git(van["repo"], "describe", "--tags").strip() == "v0.4.1"
