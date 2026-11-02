"""Schema migrations.

Migrations are plain SQL files in ``migrations/`` named ``NNN_description.sql``.
They run in order, once each. The applied version is stored in SQLite's
``PRAGMA user_version``, so no extra bookkeeping table is needed.

To change the schema, add a new file with the next number. Never edit a
migration that has already been released.
"""

from __future__ import annotations

import logging
import re
import sqlite3
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

from smartify.db.connection import connect

log = logging.getLogger(__name__)

_FILENAME = re.compile(r"^(\d{3})_[a-z0-9_]+\.sql$")


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    sql: str


def load_migrations() -> list[Migration]:
    migrations = []
    for entry in resources.files("smartify.db").joinpath("migrations").iterdir():
        match = _FILENAME.match(entry.name)
        if not match:
            continue
        migrations.append(Migration(int(match.group(1)), entry.name, entry.read_text("utf-8")))
    migrations.sort(key=lambda m: m.version)
    versions = [m.version for m in migrations]
    if versions != list(range(1, len(versions) + 1)):
        raise RuntimeError(f"Migration numbers must be 1..N without gaps, got {versions}")
    return migrations


def current_version(conn: sqlite3.Connection) -> int:
    return conn.execute("PRAGMA user_version").fetchone()[0]


def migrate(db_path: Path) -> int:
    """Apply all pending migrations and return the resulting schema version."""
    conn = connect(db_path)
    try:
        version = current_version(conn)
        for migration in load_migrations():
            if migration.version <= version:
                continue
            log.info("Applying migration %s", migration.name)
            # executescript commits any open transaction first; wrap the file
            # in its own transaction so a failing migration leaves no traces.
            conn.executescript(
                f"BEGIN;\n{migration.sql}\nPRAGMA user_version = {migration.version};\nCOMMIT;"
            )
            version = migration.version
        return version
    finally:
        conn.close()
