"""game.json helpers shared by the reporting stages: locate/load it, team display names and colours.

Source of truth for team identity is game.json:
  us.team / them.team      display names ("Us" / "Them" when missing)
  us.colour / them.colour  jersey colour words used for team clustering (build_tracks)
  us.hex / them.hex        optional chart colours (#rrggbb); neutral palette defaults when missing
Keys named `_comment` are documentation (see templates/game.example.json) and are ignored.
"""
from __future__ import annotations

import json
from pathlib import Path

SIDES = ("us", "them")
# Neutral default chart pair (validated violet / aqua on a light surface); override with us.hex / them.hex.
DEFAULT_HEX = {"us": "#6250d6", "them": "#1baf7a"}
DEFAULT_NAME = {"us": "Us", "them": "Them"}


def find_up(folder: Path | str, name: str = "game.json", levels: int = 1) -> Path | None:
    """`name` in `folder` or up to `levels` parents (a player sub-report sits one level below the game)."""
    d = Path(folder)
    for _ in range(levels + 1):
        if (d / name).exists():
            return d / name
        d = d.parent
    return None


def load_game(path: Path | str | None) -> dict:
    """Load game.json from a file path or a folder (searching one level up); {} when not found.
    A training session folder has session.json instead (`kind: "training"`), which is returned the same way, so
    clips, narrate, film and html work on sessions unchanged; a movement session has movement.json
    (`kind: "movement"`), a season folder season.json (`kind: "season"`, from `hoop-tape-miner season`)."""
    if path is None:
        return {}
    p = Path(path)
    if p.is_dir():
        p = (find_up(p) or find_up(p, "session.json", levels=0) or find_up(p, "movement.json", levels=0)
             or find_up(p, "season.json", levels=0))
        if p is None:
            return {}
    return json.loads(p.read_text(encoding="utf8"))


def is_training(game: dict) -> bool:
    return game.get("kind") == "training"


def is_movement(game: dict) -> bool:
    return game.get("kind") == "movement"


def is_season(game: dict) -> bool:
    return game.get("kind") == "season"


def is_personal(game: dict) -> bool:
    """A one-player page (training or movement session), not a game."""
    return is_training(game) or is_movement(game)


def team(game: dict, side: str) -> dict:
    t = game.get(side) or {}
    return t if isinstance(t, dict) else {}


def team_name(game: dict, side: str) -> str:
    return team(game, side).get("team") or DEFAULT_NAME[side]


def team_hex(game: dict, side: str, default: str | None = None) -> str:
    h = team(game, side).get("hex")
    return h if is_hex(h) else (default or DEFAULT_HEX[side])


def is_hex(h) -> bool:
    return isinstance(h, str) and len(h) == 7 and h.startswith("#") and all(c in "0123456789abcdefABCDEF" for c in h[1:])


def hex_to_rgb(h: str) -> tuple[int, int, int]:
    return int(h[1:3], 16), int(h[3:5], 16), int(h[5:7], 16)


def hex_to_bgr(h: str) -> tuple[int, int, int]:
    r, g, b = hex_to_rgb(h)
    return b, g, r


def mix(h: str, other: str = "#ffffff", t: float = 0.5) -> str:
    """Blend colour `h` towards `other` by fraction t (0 = h, 1 = other)."""
    a, b = hex_to_rgb(h), hex_to_rgb(other)
    return "#" + "".join(f"{round(x + (y - x) * t):02x}" for x, y in zip(a, b))
