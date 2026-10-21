"""Start a personal training session: session folder, session.json and one joined session video.

usage: hoop-tape-miner train-new <phone video> [<phone video> ...] [--player 17] [--date 2026-10-20]
           [--name "Alex"] [--plan "free throws, left-hand layups"] [--height 1080]

The phone files are joined in the given order into `session.mp4` (rotation applied, 30 fps, H.264, long side
--height px) in the media folder; their start offsets in the joined video are kept in session.json `sources`, so
every time in the report can be traced back to a phone file. Targets from the previous session's plan.json are
copied into `targets`, and the next train-summary checks them. The latest game before the session (the player's
jersey on our box score) seeds `game_focus`: that game's insights for the jersey, then the team's, with drill and
next-game target (game_link.focus). Prints the session folder.
--player defaults to team.json focus_player; --date to the first file's recording date (else its file date).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import tempfile
from pathlib import Path

from . import game_link, media
from . import training as T
from . import workspace

LONG_SIDE = 1080


def probe(p: Path) -> dict:
    """width / height after rotation, duration (s) and recording date (YYYY-MM-DD or None) of a video."""
    info = media.probe(p)
    v = next(s for s in info["streams"] if s.get("codec_type") == "video")
    w, h = int(v["width"]), int(v["height"])
    rot = int(float((v.get("tags") or {}).get("rotate", 0) or 0))
    for sd in v.get("side_data_list") or []:
        if "rotation" in sd:
            rot = int(float(sd["rotation"]))
    if rot % 180:
        w, h = h, w
    created = (info.get("format", {}).get("tags") or {}).get("creation_time") or (v.get("tags") or {}).get("creation_time")
    return dict(w=w, h=h, duration=float(info["format"]["duration"]), date=created[:10] if created else None)


def target_size(w: int, h: int, long_side: int) -> tuple[int, int]:
    """Scale so the long side is at most long_side; even numbers for H.264."""
    k = min(1.0, long_side / max(w, h))
    return int(round(w * k / 2)) * 2, int(round(h * k / 2)) * 2


def join(videos: list[Path], out: Path, long_side: int = LONG_SIDE) -> list[dict]:
    """Normalise every file to the first file's orientation and size, then concatenate; returns sources."""
    infos = [probe(v) for v in videos]
    W, H = target_size(infos[0]["w"], infos[0]["h"], long_side)
    out.parent.mkdir(parents=True, exist_ok=True)
    sources, start = [], 0.0
    with tempfile.TemporaryDirectory() as tmp:
        parts = []
        for i, (v, info) in enumerate(zip(videos, infos)):
            part = Path(tmp) / f"p{i:03d}.mp4"
            vf = (f"scale={W}:{H}:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2,setsar=1,"
                  "fps=30")
            print(f"[train-new] {v.name}: {info['duration']:.0f} s", flush=True)
            media.ffmpeg("-i", v, "-vf", vf, "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt",
                         "yuv420p", "-c:a", "aac", "-b:a", "96k", "-ar", "48000", "-ac", "1", part)
            parts.append(part)
            dur = probe(part)["duration"]
            sources.append(dict(file=str(v.resolve()), start=round(start, 2), duration=round(dur, 2)))
            start += dur
        with media.partial(out) as joined:
            media.concat(parts, joined, Path(tmp))
    return sources


def previous_targets(folder: Path) -> tuple[list[dict], str | None]:
    """Targets of the latest earlier session's plan.json (drills[].target), and that session's name."""
    for prev in reversed(T.earlier_sessions(folder)):
        p = prev / "plan.json"
        if p.exists():
            plan = json.loads(p.read_text(encoding="utf8"))
            return [d["target"] for d in plan.get("drills", []) if d.get("target")], prev.name
    return [], None


def create(videos: list[Path], player: str, date: str | None = None, name: str | None = None, plan: str = "",
           long_side: int = LONG_SIDE, joiner=join) -> Path:
    for v in videos:
        if not v.is_file():
            sys.exit(f"video not found: {v}")
    date = date or probe(videos[0])["date"] or dt.date.fromtimestamp(videos[0].stat().st_mtime).isoformat()
    sname = T.session_name(player, date)
    folder = T.sessions_root(player) / sname
    media = T.media_root_for(player) / sname
    folder.mkdir(parents=True, exist_ok=True)
    video = media / "session.mp4"
    sources = joiner(videos, video, long_side)
    targets, from_session = previous_targets(folder)
    prof = workspace.profile()
    jersey = game_link.jersey_for({"player": player}, prof)
    root = game_link.workspace_of(folder)
    focus = game_link.focus(root, jersey, date) if jersey and root else None
    s = dict(kind="training", player=str(player), name=name or "", date=date, title="",
             sources=sources, video=str(video.resolve()), run=str((media / "run").resolve()),
             hex=prof.get("hex") or "", plan=plan, targets=targets, targets_from=from_session,
             rim=[], rim_checked=False, jersey=jersey, game_focus=focus)
    (folder / "session.json").write_text(json.dumps(s, indent=2, ensure_ascii=False) + "\n", encoding="utf8")
    print(f"[train-new] session {folder}")
    print(f"[train-new] video {video} ({sum(x['duration'] for x in sources) / 60:.1f} min)")
    if targets:
        print(f"[train-new] {len(targets)} targets from {from_session}")
    if focus:
        print(f"[train-new] game focus: {len(focus['insights'])} insights from {focus['game']}")
    return folder


def main(argv=None):
    ap = argparse.ArgumentParser(prog="hoop-tape-miner train-new", description=__doc__.split("\n\n")[0])
    ap.add_argument("videos", nargs="+", help="phone video files of one workout, in recording order")
    ap.add_argument("--player", help="player number or slug (default: team.json focus_player)")
    ap.add_argument("--date", help="session date YYYY-MM-DD (default: recording date of the first file)")
    ap.add_argument("--name", help="player display name for the pages")
    ap.add_argument("--plan", default="", help="what you meant to train, in your own words")
    ap.add_argument("--height", type=int, default=LONG_SIDE, help=f"long side of session.mp4 in px (default {LONG_SIDE})")
    a = ap.parse_args(argv)
    player = a.player or workspace.profile().get("focus_player")
    if not player:
        ap.error("--player is required when team.json has no focus_player")
    return create([Path(v) for v in a.videos], str(player), a.date, a.name, a.plan, a.height)


if __name__ == "__main__":
    main()
