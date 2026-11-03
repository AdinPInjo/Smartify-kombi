#!/usr/bin/env python3
"""Smartify Kombi updater: installs a released version and undoes it if it fails.

Started by smartify-update.service when the dashboard writes
``<data dir>/update/request.json`` (Settings → Updates). It runs as the same
user as Smartify, never as root; the only extra right it has is restarting
smartify.service (a polkit rule from deploy/install.sh).

Steps, each reported in ``update/status.json`` for the dashboard:

1. Get the version: ``git fetch`` the release tag, download the prebuilt
   dashboard and check it against the release's SHA256SUMS. Nothing on the van
   changes before everything is downloaded and checked.
2. Back up the database.
3. Switch the code to the tag, install new Python packages if needed, put the
   new dashboard in place.
4. Restart Smartify and wait until it answers with the new version.
5. If it doesn't: put back the previous code, dashboard and database, start
   the old version again, and report what went wrong.

Standard library only, so it works whatever state the Python environment is in.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request
from pathlib import Path

VERSION = re.compile(r"^\d+\.\d+\.\d+$")
VERSION_IN_CODE = re.compile(r'^__version__ = "([^"]+)"', re.M)
KEEP_BACKUPS = 5
HISTORY = 20


class Failed(Exception):
    """A step failed; the message is shown in the dashboard."""


def now() -> int:
    return int(time.time())


def write_json(path: Path, data: object) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), "utf-8")
    os.replace(tmp, path)


class Updater:
    def __init__(self, repo: Path, data_dir: Path, request: dict, systemctl: list[str],
                 health_timeout: float) -> None:
        self.repo = repo
        self.dir = data_dir / "update"
        self.request = request
        self.target = request["version"]
        self.systemctl = systemctl
        self.health_timeout = health_timeout
        self.db = Path(request["db_path"])
        self.dist = Path(request["frontend_dir"]) if request.get("frontend_dir") else None
        self.download_base = request["download_base"].rstrip("/")
        self.health_url = request["health_url"]
        self.current = self.code_version()
        self.status = {
            "state": "running",
            "target": self.target,
            "from": self.current,
            "by": request.get("by", "dashboard"),
            "step": "Starting",
            "message": None,
            "started_at": now(),
            "finished_at": None,
            "log": [],
        }

    # --- reporting --------------------------------------------------------------------

    def step(self, text: str) -> None:
        print(f"▸ {text}", flush=True)
        self.status["step"] = text
        self.status["log"] = (self.status["log"] + [f"{time.strftime('%H:%M:%S')} {text}"])[-30:]
        write_json(self.dir / "status.json", self.status)

    def finish(self, state: str, message: str) -> None:
        print(f"{state}: {message}", flush=True)
        self.status.update(state=state, message=message, finished_at=now(), step=None)
        write_json(self.dir / "status.json", self.status)
        history_file = self.dir / "history.json"
        try:
            history = json.loads(history_file.read_text("utf-8"))
        except (OSError, ValueError):
            history = []
        entry = {k: self.status[k] for k in ("state", "from", "target", "by", "message",
                                                "started_at", "finished_at")}
        write_json(history_file, ([entry] + history)[:HISTORY])

    # --- helpers ----------------------------------------------------------------------

    def run(self, *cmd: str, timeout: float = 300, check: bool = True) -> subprocess.CompletedProcess:
        env = dict(os.environ, GIT_TERMINAL_PROMPT="0",
                   GIT_SSH_COMMAND="ssh -o BatchMode=yes -o ConnectTimeout=20")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env)
        if check and result.returncode != 0:
            detail = (result.stderr or result.stdout).strip().splitlines()
            raise Failed(f"{' '.join(cmd[:3])} failed: {detail[-1] if detail else result.returncode}")
        return result

    def git(self, *args: str, **kwargs) -> subprocess.CompletedProcess:
        return self.run("git", "-C", str(self.repo), *args, **kwargs)

    def code_version(self) -> str:
        text = (self.repo / "backend/smartify/__init__.py").read_text("utf-8")
        match = VERSION_IN_CODE.search(text)
        return match.group(1) if match else "unknown"

    def download(self, url: str, target: Path) -> None:
        try:
            with urllib.request.urlopen(url, timeout=60) as response, open(target, "wb") as out:
                shutil.copyfileobj(response, out)
        except Exception as exc:  # noqa: BLE001 - any network problem
            raise Failed(f"download failed ({url.rsplit('/', 1)[-1]}): {exc}") from None

    def service(self, action: str) -> int:
        result = subprocess.run([*self.systemctl, action, "smartify"], capture_output=True,
                                text=True, timeout=180)
        if result.returncode != 0:
            print(f"  systemctl {action}: {result.stderr.strip()}", flush=True)
        return result.returncode

    def wait_for(self, version: str) -> bool:
        deadline = time.monotonic() + self.health_timeout
        while time.monotonic() < deadline:
            try:
                with urllib.request.urlopen(self.health_url, timeout=5) as response:
                    if json.load(response).get("version") == version:
                        return True
            except Exception:  # noqa: BLE001 - not up yet
                pass
            time.sleep(2)
        return False

    def pyproject_differs(self, a: str, b: str) -> bool:
        return self.git("diff", "--quiet", a, b, "--", "backend/pyproject.toml",
                        check=False).returncode != 0

    def pip_install(self) -> None:
        pip = self.repo / "backend/.venv/bin/pip"
        if pip.exists():
            self.run(str(pip), "install", "-q", "-e", f"{self.repo / 'backend'}[pi]", timeout=1800)

    # --- the update ---------------------------------------------------------------------

    def prepare(self, work: Path) -> Path | None:
        """Everything that can fail without changing the van. Returns the new dashboard."""
        self.step("Checking this installation")
        if self.git("status", "--porcelain", "--untracked-files=no").stdout.strip():
            raise Failed("this copy has local code changes; update it with git instead")
        if shutil.disk_usage(self.repo).free < 200 * 1024 * 1024:
            raise Failed("less than 200 MB free on the SD card")

        self.step(f"Getting version {self.target}")
        tag = f"v{self.target}"
        self.git("fetch", "--force", "--tags", "--quiet", "origin", timeout=300)
        if self.git("rev-parse", "--verify", "--quiet", f"{tag}^{{commit}}", check=False).returncode:
            raise Failed(f"version {self.target} was not found in the project")
        tagged = self.git("show", f"{tag}:backend/smartify/__init__.py").stdout
        match = VERSION_IN_CODE.search(tagged)
        if not match or match.group(1) != self.target:
            raise Failed(f"the tag {tag} does not contain version {self.target}")

        if self.dist is None:
            return None
        self.step("Downloading the dashboard")
        base = f"{self.download_base}/{tag}"
        sums, archive = work / "SHA256SUMS", work / "dashboard.tar.gz"
        self.download(f"{base}/SHA256SUMS", sums)
        self.download(f"{base}/dashboard.tar.gz", archive)
        expected = next((line.split()[0] for line in sums.read_text().splitlines()
                         if line.strip().endswith("dashboard.tar.gz")), None)
        actual = hashlib.sha256(archive.read_bytes()).hexdigest()
        if expected != actual:
            raise Failed("the downloaded dashboard does not match its checksum; try again later")
        new = self.dist.with_name(self.dist.name + ".new")
        shutil.rmtree(new, ignore_errors=True)
        new.mkdir(parents=True)
        with tarfile.open(archive) as tar:
            for member in tar.getmembers():
                name = os.path.normpath(member.name)
                if name.startswith(("/", "..")) or "/../" in f"/{name}/":
                    raise Failed("the dashboard archive contains unsafe paths")
                if name == ".":
                    continue
                if member.isdir():
                    (new / name).mkdir(parents=True, exist_ok=True)
                elif member.isfile():
                    (new / name).parent.mkdir(parents=True, exist_ok=True)
                    with tar.extractfile(member) as src, open(new / name, "wb") as dst:  # type: ignore[union-attr]
                        shutil.copyfileobj(src, dst)
        if not (new / "index.html").is_file():
            raise Failed("the downloaded dashboard is incomplete")
        return new

    def backup_database(self) -> Path | None:
        if not self.db.is_file():
            return None
        self.step("Backing up your data")
        folder = self.db.parent / "backups"
        folder.mkdir(exist_ok=True)
        target = folder / f"before-update-{self.current}-to-{self.target}-{time.strftime('%Y%m%d-%H%M%S')}.db"
        src, dst = sqlite3.connect(self.db), sqlite3.connect(target)
        try:
            src.backup(dst)
        finally:
            src.close()
            dst.close()
        for old in sorted(folder.glob("before-update-*.db"))[:-KEEP_BACKUPS]:
            old.unlink(missing_ok=True)
        return target

    def swap_dashboard(self, new: Path | None) -> None:
        if new is None or self.dist is None:
            return
        previous = self.dist.with_name(self.dist.name + ".previous")
        shutil.rmtree(previous, ignore_errors=True)
        if self.dist.exists():
            os.replace(self.dist, previous)
        os.replace(new, self.dist)

    def restore_dashboard(self) -> None:
        if self.dist is None:
            return
        previous = self.dist.with_name(self.dist.name + ".previous")
        if previous.exists():
            shutil.rmtree(self.dist, ignore_errors=True)
            os.replace(previous, self.dist)

    def restore_database(self, backup: Path | None) -> None:
        if backup is None:
            return
        for suffix in ("-wal", "-shm"):
            Path(f"{self.db}{suffix}").unlink(missing_ok=True)
        shutil.copyfile(backup, self.db)

    def update(self) -> None:
        with tempfile.TemporaryDirectory(prefix="smartify-update-") as tmp:
            try:
                new_dashboard = self.prepare(Path(tmp))
                old_ref = self.git("rev-parse", "HEAD").stdout.strip()
                branch = self.git("symbolic-ref", "--short", "-q", "HEAD", check=False).stdout.strip()
                backup = self.backup_database()
            except (Failed, subprocess.TimeoutExpired, OSError, sqlite3.Error) as exc:
                if self.dist is not None:
                    shutil.rmtree(self.dist.with_name(self.dist.name + ".new"), ignore_errors=True)
                self.finish("failed", f"Not updated: {exc}. Nothing was changed.")
                return

            tag = f"v{self.target}"
            try:
                self.step(f"Installing {self.target}")
                self.git("-c", "advice.detachedHead=false", "checkout", "--quiet", "--detach", tag)
                if self.pyproject_differs(old_ref, tag):
                    self.step("Installing new Python packages (a few minutes on a Pi 3)")
                    self.pip_install()
                self.swap_dashboard(new_dashboard)
                self.step("Restarting Smartify")
                self.service("restart")
                self.step("Checking that everything runs")
                if not self.wait_for(self.target):
                    raise Failed(f"version {self.target} did not start properly")
            except (Failed, subprocess.TimeoutExpired, OSError) as exc:
                self.roll_back(old_ref, branch, backup, str(exc))
                return

        if self.dist is not None:
            shutil.rmtree(self.dist.with_name(self.dist.name + ".previous"), ignore_errors=True)
        self.finish("done", f"Updated from {self.current} to {self.target}.")

    def roll_back(self, old_ref: str, branch: str, backup: Path | None, error: str) -> None:
        self.step(f"Going back to {self.current}")
        try:
            self.service("stop")
            if branch:
                self.git("checkout", "--quiet", "--force", branch)
            else:
                self.git("-c", "advice.detachedHead=false", "checkout", "--quiet", "--force", old_ref)
            if self.pyproject_differs(old_ref, f"v{self.target}"):
                self.pip_install()
            self.restore_dashboard()
            self.restore_database(backup)
            self.service("start")
            ok = self.wait_for(self.current)
        except (Failed, subprocess.TimeoutExpired, OSError) as exc:
            print(f"rollback problem: {exc}", flush=True)
            ok = False
        if ok:
            self.finish("rolled_back",
                        f"The update to {self.target} did not work ({error}), so Smartify went back to "
                        f"{self.current}. Your settings and data are as they were before.")
        else:
            self.finish("failed",
                        f"The update to {self.target} did not work ({error}) and {self.current} does not "
                        "start again either. On the Pi, run: cd ~/smartify-kombi && sudo ./deploy/install.sh")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data-dir", required=True, type=Path)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument("--systemctl", default="systemctl", help="command used to restart Smartify")
    parser.add_argument("--health-timeout", type=float, default=180)
    args = parser.parse_args(argv)

    folder = args.data_dir / "update"
    request_file = folder / "request.json"
    try:
        request = json.loads(request_file.read_text("utf-8"))
    except (OSError, ValueError):
        print("no valid update request", file=sys.stderr)
        return 0
    finally:
        request_file.unlink(missing_ok=True)  # never start the same request twice
    if not isinstance(request, dict) or not VERSION.match(str(request.get("version", ""))):
        print("update request without a valid version", file=sys.stderr)
        return 0

    with open(folder / "updater.lock", "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("an update is already running", file=sys.stderr)
            return 0
        updater = Updater(args.repo.resolve(), args.data_dir.resolve(), request,
                          args.systemctl.split(), args.health_timeout)
        if request["version"] == updater.current:
            updater.finish("done", f"Version {updater.current} is already installed.")
            return 0
        updater.update()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
