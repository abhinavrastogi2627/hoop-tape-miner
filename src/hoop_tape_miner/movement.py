"""Movement sessions (running form, force pattern, layup approach): folder layout, movement.json, segment times.

A movement session is `<workspace>/players/<player>/movement/<YYYY-MM-DD>[-n]/movement.json`; heavy files (the
reel, pose per segment) go under `<media_root>/players/<player>/movement/<name>/`. Each segment is one window of a
source video (a phone clip, a training session, a game) with a kind and a camera view; move-new joins them into one
reel so clips, html and film work on one video. See docs/playbook.md "Movement sessions".
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from . import workspace

KINDS = ("sprint", "run", "dribble-sprint", "layup", "decel", "game", "training")
VIEWS = ("side", "front", "behind", "game")
REEL_FPS, REEL_W, REEL_H = 30, 1280, 720
SCAN_FPS_CAP = 120.0

# Reference bands copied from prompts/movement_kb.md "Reference values"; a metric without a band is shown without one.
# {metric key: {"band": (lo, hi), "kinds": kinds it applies to, "phase": ..., "kb": slug}}
REFERENCE: dict[str, dict] = {}


def root(player: str) -> Path:
    return workspace.root() / "players" / str(player) / "movement"


def media_root_for(player: str, prof: dict | None = None) -> Path:
    media_root = (workspace.profile() if prof is None else prof).get("media_root")
    if media_root:
        return Path(media_root).expanduser() / "players" / str(player) / "movement"
    return root(player)


def session_name(player: str, date: str) -> str:
    """'2026-10-20', or '2026-10-20-2' when that day already has a movement session."""
    name, n = date, 2
    while (root(player) / name / "movement.json").exists():
        name, n = f"{date}-{n}", n + 1
    return name


def is_movement(folder: Path) -> bool:
    return (Path(folder) / "movement.json").exists()


def load(folder: Path) -> dict:
    return json.loads((Path(folder) / "movement.json").read_text(encoding="utf8"))


def save(folder: Path, m: dict) -> None:
    (Path(folder) / "movement.json").write_text(json.dumps(m, indent=2, ensure_ascii=False) + "\n", encoding="utf8")


def path(folder: Path, m: dict, key: str, default: str) -> Path:
    """movement.json path value (absolute, or relative to the session folder), else folder/default."""
    v = m.get(key)
    p = Path(v).expanduser() if v else Path(default)
    return p if p.is_absolute() else Path(folder) / p


def earlier(folder: Path) -> list[Path]:
    """Sibling movement sessions that sort before this one, oldest first."""
    folder = Path(folder)
    return sorted(d for d in folder.parent.iterdir()
                  if d.is_dir() and d.name < folder.name and is_movement(d) and re.match(r"\d{4}-\d{2}-\d{2}", d.name))


def secs(v) -> float:
    """'31:46.5' -> 1906.5, '1:02:03' -> 3723, 12 -> 12.0."""
    if isinstance(v, (int, float)):
        return float(v)
    parts = [float(x) for x in str(v).strip().split(":")]
    out = 0.0
    for x in parts:
        out = out * 60 + x
    return out


def seg_seconds(seg: dict) -> tuple[float, float]:
    """(from, to) of a segment in source seconds."""
    return secs(seg["from"]), secs(seg["to"])


def slowmo(seg: dict) -> float:
    """How many times slower than real life the source file plays (an exported phone slow-mo: 4 or 8; default 1).
    Real seconds = file seconds / slowmo; real fps = file fps * slowmo."""
    return float(seg.get("slowmo") or 1.0)
