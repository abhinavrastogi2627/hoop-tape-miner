"""Where per-game data lives: a gitignored workspace, never the repo's tracked files.

Layout: <workspace>/teams/<opponent-slug>/<date>/  game.json, official.json, README*.md, figures, run/
The workspace root is $HOOP_WORKSPACE when set, else ./workspace (relative to the current directory).
Team profile: <workspace>/team.json (template templates/team.example.json), read by `profile()`.
Heavy files (videos, run/, raw league data) go to `media_dir()`: <media_root>/teams/<slug>/<date> when the profile
sets media_root, else the game folder itself.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path


def root() -> Path:
    env = os.environ.get("HOOP_WORKSPACE")
    return Path(env).expanduser() if env else Path.cwd() / "workspace"


WINDOWS_RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}


def slug(name: str) -> str:
    """Folder name for a team, safe on Windows: lowercase, every run of characters other than letters and
    digits -> '-' ("Red Foxes" -> "red-foxes", "Bulls/Bears" -> "bulls-bears"); "team" when nothing is left."""
    s = re.sub(r"[\W_]+", "-", name.lower()).strip("-") or "team"
    return f"{s}-team" if s in WINDOWS_RESERVED else s


def _legacy_slug(name: str) -> str:
    """The slug used before 2026-10-21 (only whitespace replaced); existing folders keep that name."""
    return re.sub(r"\s+", "-", name.strip().lower())


def _slug_dir(parent: Path, name: str) -> Path:
    """parent/slug(name), or an existing parent/<legacy slug> folder made by an older version."""
    old = parent / _legacy_slug(name)
    return old if old.name != slug(name) and old.is_dir() else parent / slug(name)


def team_dir(opponent: str) -> Path:
    return _slug_dir(root() / "teams", opponent)


def game_dir(opponent: str, date: str) -> Path:
    return team_dir(opponent) / date


def profile() -> dict:
    """<workspace>/team.json without its _comment keys; {} when missing."""
    p = root() / "team.json"
    if not p.exists():
        return {}
    data = json.loads(p.read_text(encoding="utf8"))
    return {k: v for k, v in data.items() if k != "_comment"} if isinstance(data, dict) else {}


def media_dir(opponent: str, date: str, prof: dict | None = None) -> Path:
    media_root = (profile() if prof is None else prof).get("media_root")
    if media_root:
        return _slug_dir(Path(media_root).expanduser() / "teams", opponent) / date
    return game_dir(opponent, date)
