"""Scenes: one tap puts several relays into a chosen state.

A scene says, per relay, ``on`` or ``off`` (manual, until changed again) or
``auto`` (back to its rules). Relays a scene doesn't mention stay as they are.
Running a scene goes through the normal relay service, so minimum on/off times,
temperature cut-offs and the event log apply as usual.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

from smartify.db import transaction
from smartify.errors import Conflict, InvalidInput, NotFound
from smartify.services.relays import RelayService

Action = Literal["on", "off", "auto"]
ACTIONS = ("on", "off", "auto")
ICONS = ("moon", "sun", "door", "flame", "snowflake", "coffee", "bed", "car", "power", "star")
MAX_SCENES = 8


@dataclass
class Scene:
    id: int
    name: str
    icon: str
    actions: dict[str, Action]
    position: int
    active: bool = False
    """Every relay in the scene is currently set the way the scene says."""


class SceneService:
    def __init__(self, db_path: Path, relays: RelayService, clock: Callable[[], float] = time.time):
        self._db = db_path
        self._relays = relays
        self._clock = clock

    def _validate(
        self, name: str, icon: str, actions: dict[str, Any]
    ) -> tuple[str, str, dict[str, Action]]:
        name = name.strip()
        if not name or len(name) > 30:
            raise InvalidInput("a scene needs a name of up to 30 characters")
        if icon not in ICONS:
            raise InvalidInput(f"icon must be one of {', '.join(ICONS)}")
        if not isinstance(actions, dict) or not actions:
            raise InvalidInput("choose what the scene does with at least one switch")
        known = {relay.id for relay in self._relays.list()}
        clean: dict[str, Action] = {}
        for relay_id, action in actions.items():
            if relay_id not in known:
                raise InvalidInput(f"unknown switch {relay_id!r}")
            if action not in ACTIONS:
                raise InvalidInput("each switch in a scene is on, off or auto")
            clean[relay_id] = action
        return name, icon, clean

    def _active(self, actions: dict[str, Action]) -> bool:
        relays = {relay.id: relay for relay in self._relays.list()}
        for relay_id, action in actions.items():
            relay = relays.get(relay_id)
            if relay is None:
                continue
            if action == "auto" and relay.mode != "auto":
                return False
            if action != "auto" and (relay.mode != "manual" or relay.manual_state != action):
                return False
        return True

    def _scene(self, row: Any) -> Scene:
        actions = json.loads(row["actions"])
        return Scene(
            row["id"], row["name"], row["icon"], actions, row["position"], self._active(actions)
        )

    def list(self) -> list[Scene]:
        with transaction(self._db) as conn:
            rows = conn.execute("SELECT * FROM scenes ORDER BY position, id").fetchall()
        return [self._scene(row) for row in rows]

    def get(self, scene_id: int) -> Scene:
        with transaction(self._db) as conn:
            row = conn.execute("SELECT * FROM scenes WHERE id = ?", (scene_id,)).fetchone()
        if row is None:
            raise NotFound(f"scene {scene_id} not found")
        return self._scene(row)

    def create(self, name: str, icon: str, actions: dict[str, Any]) -> Scene:
        name, icon, actions = self._validate(name, icon, actions)
        now = int(self._clock())
        with transaction(self._db) as conn:
            count, last = conn.execute(
                "SELECT COUNT(*), COALESCE(MAX(position), -1) FROM scenes"
            ).fetchone()
            if count >= MAX_SCENES:
                raise Conflict(f"up to {MAX_SCENES} scenes")
            cursor = conn.execute(
                "INSERT INTO scenes (name, icon, actions, position, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (name, icon, json.dumps(actions), last + 1, now, now),
            )
            scene_id = int(cursor.lastrowid or 0)
        return self.get(scene_id)

    def update(self, scene_id: int, changes: dict[str, Any]) -> Scene:
        scene = self.get(scene_id)
        name, icon, actions = self._validate(
            changes.get("name", scene.name),
            changes.get("icon", scene.icon),
            changes.get("actions", scene.actions),
        )
        position = int(changes.get("position", scene.position))
        with transaction(self._db) as conn:
            conn.execute(
                "UPDATE scenes SET name = ?, icon = ?, actions = ?, position = ?, updated_at = ? "
                "WHERE id = ?",
                (name, icon, json.dumps(actions), position, int(self._clock()), scene_id),
            )
        return self.get(scene_id)

    def delete(self, scene_id: int) -> None:
        self.get(scene_id)
        with transaction(self._db) as conn:
            conn.execute("DELETE FROM scenes WHERE id = ?", (scene_id,))

    def run(self, scene_id: int, source: str = "scene") -> dict[str, Any]:
        """Apply a scene. Relays removed since the scene was made are skipped."""
        scene = self.get(scene_id)
        known = {relay.id for relay in self._relays.list()}
        applied, skipped = [], []
        for relay_id, action in scene.actions.items():
            if relay_id not in known:
                skipped.append(relay_id)
                continue
            if action == "auto":
                self._relays.set_auto(relay_id)
            else:
                self._relays.set_manual(relay_id, action, None, source=source)  # type: ignore[arg-type]
            applied.append(relay_id)
        return {"scene": asdict(self.get(scene_id)), "applied": applied, "skipped": skipped}
