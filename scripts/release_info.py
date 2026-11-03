#!/usr/bin/env python3
"""Release helpers, used by .github/workflows/release.yml (standard library only).

  release_info.py check 0.4.0          the version is in CHANGELOG.md and in every version file
  release_info.py notes 0.4.0          the CHANGELOG.md section of that version (release text)
  release_info.py versions 0.4.0 OUT   versions.json: every version up to 0.4.0, newest first

versions.json is attached to every release. Vans and remote dashboards read it
from .../releases/latest/download/versions.json to see what is new, without the
GitHub API (whose rate limit shared hosting runs into).
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HEADING = re.compile(r"^## (\d+\.\d+\.\d+)(?:\s*[-–—]\s*(\d{4}-\d{2}-\d{2}))?\s*$")
VERSION_FILES = {
    "backend/pyproject.toml": re.compile(r'^version = "([^"]+)"', re.M),
    "backend/smartify/__init__.py": re.compile(r'^__version__ = "([^"]+)"', re.M),
    "frontend/package.json": re.compile(r'^  "version": "([^"]+)"', re.M),
    "cloud/api/lib.php": re.compile(r"^const SMARTIFY_CLOUD_VERSION = '([^']+)'", re.M),
}


def key(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


def parse_changelog(text: str) -> list[dict]:
    """Sections of CHANGELOG.md as {version, date, notes}, in file order."""
    entries: list[dict] = []
    current: dict | None = None
    for line in text.splitlines():
        match = HEADING.match(line)
        if match:
            current = {"version": match.group(1), "date": match.group(2), "lines": []}
            entries.append(current)
        elif line.startswith("## "):
            current = None  # e.g. "## Unreleased"
        elif current is not None:
            current["lines"].append(line)
    return [
        {"version": e["version"], "date": e["date"], "notes": "\n".join(e["lines"]).strip()}
        for e in entries
    ]


def changelog() -> list[dict]:
    return parse_changelog((ROOT / "CHANGELOG.md").read_text("utf-8"))


def check(version: str) -> list[str]:
    problems = []
    entry = next((e for e in changelog() if e["version"] == version), None)
    if entry is None:
        problems.append(f"CHANGELOG.md has no '## {version} - YYYY-MM-DD' section")
    elif not entry["notes"]:
        problems.append(f"the CHANGELOG.md section for {version} is empty")
    for path, pattern in VERSION_FILES.items():
        match = pattern.search((ROOT / path).read_text("utf-8"))
        found = match.group(1) if match else "nothing"
        if found != version:
            problems.append(f"{path} says {found}, the tag says {version}")
    return problems


def versions(up_to: str) -> list[dict]:
    entries = [e for e in changelog() if key(e["version"]) <= key(up_to)]
    return sorted(entries, key=lambda e: key(e["version"]), reverse=True)


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    command, version = argv[0], argv[1].removeprefix("v")
    if command == "check":
        problems = check(version)
        for problem in problems:
            print(f"✗ {problem}", file=sys.stderr)
        if not problems:
            print(f"✓ {version}: changelog and version files agree")
        return 1 if problems else 0
    if command == "notes":
        entry = next((e for e in changelog() if e["version"] == version), None)
        print(entry["notes"] if entry else "")
        return 0
    if command == "versions" and len(argv) == 3:
        data = {"schema": 1, "latest": version, "versions": versions(version)}
        Path(argv[2]).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", "utf-8")
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
