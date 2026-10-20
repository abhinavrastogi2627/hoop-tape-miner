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
# {key: {"metric": gait key, "band": (lo, hi), "phase": accel | maxv | layup | dribble, "kinds": segment kinds,
# "kb": slug}}. accel = mean of the first `steps` steps, maxv = mean of the steps from step 9 on (a long side-view run).
_ACCEL, _MAXV = ("sprint", "dribble-sprint"), ("sprint", "run")
REFERENCE: dict[str, dict] = {
    "trunk_lean@accel": dict(metric="trunk_lean", band=(48, 64), phase="accel", steps=3, kinds=_ACCEL,
                             kb="MV-accel-posture", unit="°"),
    "trunk_lean@maxv": dict(metric="trunk_lean", band=(9, 20), phase="maxv", kinds=_MAXV, kb="MV-accel-posture",
                            unit="°"),
    "shin@accel": dict(metric="shin", band=(32, 38), phase="accel", steps=3, kinds=_ACCEL, kb="MV-braking-touchdown",
                       unit="°"),
    "touchdown_ahead@accel": dict(metric="touchdown_ahead", band=(-0.15, 0.07), phase="accel", steps=4, kinds=_ACCEL,
                                  kb="MV-braking-touchdown", unit="leg"),
    "contact_s@accel": dict(metric="contact_s", band=(0.175, 0.203), phase="accel", steps=4, kinds=_ACCEL,
                            kb="MV-short-accel-stride", unit="s"),
    "contact_s@maxv": dict(metric="contact_s", band=(0.13, 0.16), phase="maxv", kinds=_MAXV,
                           kb="MV-ankle-dominant-push", unit="s"),
    "cadence_spm@accel": dict(metric="cadence_spm", band=(238, 273), phase="accel", steps=4, kinds=_ACCEL,
                              kb="MV-short-accel-stride", unit="/min"),
    "cadence_spm@maxv": dict(metric="cadence_spm", band=(283, 302), phase="maxv", kinds=_MAXV,
                             kb="MV-short-accel-stride", unit="/min"),
    "penultimate_ratio": dict(metric="penultimate_ratio", band=(1.0, 1.4), phase="layup", kinds=("layup",),
                              kb="MV-layup-penultimate", unit="x"),
    "hip_drop": dict(metric="hip_drop", band=(0.02, 0.08), phase="layup", kinds=("layup",), kb="MV-layup-penultimate",
                     unit="leg"),
    "takeoff_ahead": dict(metric="takeoff_ahead", band=(0.0, 0.3), phase="layup", kinds=("layup",),
                          kb="MV-one-foot-takeoff", unit="leg"),
    "free_knee": dict(metric="free_knee", band=(75, 95), phase="layup", kinds=("layup",), kb="MV-one-foot-takeoff",
                      unit="°"),
    "takeoff_knee": dict(metric="takeoff_knee", band=None, phase="layup", kinds=("layup",), kb="MV-one-foot-takeoff",
                         unit="°"),
    "landing_knee_min": dict(metric="landing_knee_min", band=None, phase="layup", kinds=("layup",), kb="MV-landing",
                             unit="°"),
    "bounces_per_10m": dict(metric="bounces_per_10m", band=(1.1, 1.8), phase="dribble", kinds=("dribble-sprint",),
                            kb="MV-speed-dribble", unit=""),
    "ball_top_vs_hip": dict(metric="ball_top_vs_hip", band=(0.9, 1.15), phase="dribble", kinds=("dribble-sprint",),
                            kb="MV-speed-dribble", unit="leg"),
}
MAXV_FROM_STEP = 8
# Running faults: from a non-side camera they stay hypotheses for the re-shoot, never "seen".
SPRINT_SLUGS = ("MV-accel-posture", "MV-braking-touchdown", "MV-ankle-dominant-push", "MV-short-accel-stride",
                "MV-backside-mechanics")


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
