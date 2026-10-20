"""Start (or extend) a movement session: movement.json with segments and one viewing reel.

usage: hoop-tape-miner move-new --spec segments.json [--player 17] [--date 2026-10-20] [--name "Alex"] [--plan ...]
       hoop-tape-miner move-new <phone clip> [...] --kind sprint --view side [--slowmo 8] [--player ..]
       hoop-tape-miner move-new --into <movement folder> (--spec more.json | <phone clip> ... --kind .. --view ..)

A segment is one window of a source video: {"id", "kind", "view", "source", "from", "to", "crop"?, "seed"?,
"release"?, "slowmo"?, "note"}. kind: sprint, run, dribble-sprint, layup, decel, game, training; view: side, front,
behind, game. --spec is a JSON list of segments or {"look": "...", "segments": [...]}; phone clips given directly
become whole-file segments. "crop" = [x, y, w, h] frame fractions; "seed" = [x, y] frame fractions of the player at
the segment start; "release" = ball release time of a layup (source time); "slowmo" = how many times slower than
real life an exported slow-motion file plays (keep the original 120/240 fps file when you can: then leave it out).
Every window is cut, letterboxed to 1280x720 at 30 fps and joined into `reel.mp4` in the media folder; each
segment's place in the reel is kept as reel_from / reel_to. Prints the session folder.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from . import movement as M
from . import workspace


def probe(p: Path) -> dict:
    """duration (s) and frame rate of a video file."""
    out = subprocess.run([os.environ.get("FFPROBE", "ffprobe"), "-v", "error", "-print_format", "json",
                          "-show_format", "-show_streams", str(p)], capture_output=True, text=True, check=True).stdout
    info = json.loads(out)
    v = next(s for s in info["streams"] if s.get("codec_type") == "video")
    num, den = (v.get("avg_frame_rate") or v.get("r_frame_rate") or "30/1").split("/")
    fps = float(num) / float(den) if float(den) else 30.0
    return dict(duration=float(info["format"]["duration"]), fps=fps)


def reel_plan(segments: list[dict], durations: dict[str, float], fps: dict[str, float]) -> list[dict]:
    """Checked copies of the segments with id (S01..), reel_from / reel_to (nominal, seconds in the reel), fps (file),
    scan_fps (file frames per second to analyse: real fps capped at SCAN_FPS_CAP) and real_fps. Raises ValueError
    naming the segment for an unknown source, kind or view, or a window outside the file."""
    out, at, seen = [], 0.0, set()
    for n, seg in enumerate(segments, 1):
        s = dict(seg)
        s["id"] = s.get("id") or f"S{n:02d}"
        sid = s["id"]
        if sid in seen:
            raise ValueError(f"segment {sid}: duplicate id")
        seen.add(sid)
        src = str(s.get("source") or "")
        if src not in durations:
            raise ValueError(f"segment {sid}: source not found: {src}")
        if s.get("kind") not in M.KINDS:
            raise ValueError(f"segment {sid}: kind must be one of {', '.join(M.KINDS)}")
        if s.get("view") not in M.VIEWS:
            raise ValueError(f"segment {sid}: view must be one of {', '.join(M.VIEWS)}")
        s.setdefault("from", 0)
        s.setdefault("to", durations[src])
        a, b = M.seg_seconds(s)
        if not 0 <= a < b <= durations[src] + 0.05:
            raise ValueError(f"segment {sid}: window {s['from']}-{s['to']} is outside {src} "
                             f"(0-{durations[src]:.1f} s)")
        f, k = float(fps[src]), M.slowmo(s)
        s["fps"] = round(f, 3)
        s["scan_fps"] = round(min(f, M.SCAN_FPS_CAP / k), 3)
        s["real_fps"] = round(s["scan_fps"] * k, 3)
        s["reel_from"], s["reel_to"] = round(at, 3), round(at + b - a, 3)
        at += b - a
        out.append(s)
    return out


def place(segments: list[dict], part_durations: list[float]) -> list[dict]:
    """reel_from / reel_to from the real length of each cut part (frame rounding makes them drift otherwise)."""
    at = 0.0
    for s, d in zip(segments, part_durations):
        s["reel_from"], s["reel_to"] = round(at, 3), round(at + d, 3)
        at += d
    return segments


def build_reel(segments: list[dict], out: Path, w: int = M.REEL_W, h: int = M.REEL_H) -> list[float]:
    """Cut each window (optional crop), letterbox to w x h at 30 fps, no audio, and join into `out`; returns the
    length of each part in seconds."""
    ffmpeg = os.environ.get("FFMPEG", "ffmpeg")
    out.parent.mkdir(parents=True, exist_ok=True)
    durs = []
    with tempfile.TemporaryDirectory() as tmp:
        parts = []
        for s in segments:
            a, b = M.seg_seconds(s)
            vf = []
            if s.get("crop"):
                cx, cy, cw, ch = s["crop"]
                vf.append(f"crop=iw*{cw}:ih*{ch}:iw*{cx}:ih*{cy}")
            vf.append(f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,setsar=1,"
                      f"fps={M.REEL_FPS}")
            part = Path(tmp) / f"{s['id']}.mp4"
            print(f"[move-new] {s['id']} {s['kind']}/{s['view']} {Path(s['source']).name} {s['from']}-{s['to']}",
                  flush=True)
            subprocess.run([ffmpeg, "-nostdin", "-v", "error", "-y", "-ss", f"{a:.3f}", "-i", s["source"],
                            "-t", f"{b - a:.3f}", "-vf", ",".join(vf), "-an", "-c:v", "libx264", "-preset", "veryfast",
                            "-crf", "20", "-pix_fmt", "yuv420p", str(part)], check=True)
            parts.append(part)
            durs.append(probe(part)["duration"])
        lst = Path(tmp) / "list.txt"
        lst.write_text("".join(f"file '{p.as_posix()}'\n" for p in parts), encoding="utf8")
        subprocess.run([ffmpeg, "-nostdin", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
                        "-c", "copy", "-movflags", "+faststart", str(out)], check=True)
    return durs


def read_spec(p: Path) -> tuple[list[dict], dict]:
    """Segments and extra top-level keys (look, plan, name) from a spec file."""
    d = json.loads(Path(p).read_text(encoding="utf8"))
    if isinstance(d, list):
        return d, {}
    return d.get("segments", []), {k: v for k, v in d.items() if k != "segments"}


def create(segments: list[dict], player: str | None = None, date: str | None = None, name: str | None = None,
           plan: str = "", look: str = "", into: Path | None = None, prober=probe, builder=build_reel) -> Path:
    """Write movement.json and the reel; with `into`, append the segments to that session and rebuild its reel."""
    if into:
        folder = Path(into)
        m = M.load(folder)
        old = m.get("segments", [])
        n0 = len(old)
        for i, s in enumerate(segments, 1):
            s.setdefault("id", f"S{n0 + i:02d}")
        segments = [{k: v for k, v in s.items() if k not in ("reel_from", "reel_to")} for s in old] + segments
        media = M.path(folder, m, "video", "reel.mp4").parent
    else:
        srcs = [Path(s["source"]) for s in segments if s.get("source")]
        date = date or (dt.date.fromtimestamp(srcs[0].stat().st_mtime).isoformat() if srcs and srcs[0].exists()
                        else dt.date.today().isoformat())
        sname = M.session_name(player, date)
        folder = M.root(player) / sname
        media = M.media_root_for(player) / sname
        m = dict(kind="movement", player=str(player), name=name or "", date=date, title="", hex="", look=look,
                 plan=plan, video=str((media / "reel.mp4").resolve()), video_overlay="",
                 run=str((media / "run").resolve()), labels_checked=False)
    for s in segments:
        s["source"] = str(Path(s["source"]).resolve()) if s.get("source") else ""
    info = {}
    for src in {s["source"] for s in segments}:
        if Path(src).is_file():
            info[src] = prober(Path(src))
    try:
        plan_segs = reel_plan(segments, {k: v["duration"] for k, v in info.items()}, {k: v["fps"] for k, v in info.items()})
    except ValueError as e:
        sys.exit(f"[move-new] {e}")
    folder.mkdir(parents=True, exist_ok=True)
    reel = Path(m["video"]) if into else media / "reel.mp4"
    tmp_reel = reel.with_name(reel.stem + ".tmp.mp4")
    durs = builder(plan_segs, tmp_reel)
    os.replace(tmp_reel, reel)
    m["segments"] = place(plan_segs, durs)
    m["video_overlay"] = ""  # stale after a rebuild; move-sheets draws it again
    M.save(folder, m)
    print(f"[move-new] session {folder}")
    print(f"[move-new] reel {reel} ({len(plan_segs)} segments, {sum(durs):.0f} s)")
    return folder


def main(argv=None):
    ap = argparse.ArgumentParser(prog="hoop-tape-miner move-new", description=__doc__.split("\n\n")[0])
    ap.add_argument("videos", nargs="*", help="phone clips, each one whole-file segment (needs --kind and --view)")
    ap.add_argument("--spec", help="JSON list of segments, or {\"look\": .., \"segments\": [..]}")
    ap.add_argument("--kind", choices=M.KINDS, help="kind of the phone clips given directly")
    ap.add_argument("--view", choices=M.VIEWS, help="camera view of the phone clips given directly")
    ap.add_argument("--slowmo", type=float, help="the clips are exported slow motion playing this many times slower")
    ap.add_argument("--into", help="add the segments to this movement session and rebuild its reel")
    ap.add_argument("--player", help="player number or slug (default: team.json focus_player)")
    ap.add_argument("--date", help="session date YYYY-MM-DD (default: first source's file date)")
    ap.add_argument("--name", help="player display name for the pages")
    ap.add_argument("--plan", default="", help="what this session is for, in your own words")
    ap.add_argument("--look", default="", help="what the player wears, so reviewers can tell them apart")
    a = ap.parse_args(argv)
    segs, extra = read_spec(Path(a.spec)) if a.spec else ([], {})
    if a.videos:
        if not (a.kind and a.view):
            ap.error("phone clips need --kind and --view")
        segs += [dict(kind=a.kind, view=a.view, source=v, **({"slowmo": a.slowmo} if a.slowmo else {}))
                 for v in a.videos]
    if not segs:
        ap.error("give --spec or phone clips")
    if a.into:
        return create(segs, into=Path(a.into))
    player = a.player or extra.get("player") or workspace.profile().get("focus_player")
    if not player:
        ap.error("--player is required when team.json has no focus_player")
    return create(segs, str(player), a.date or extra.get("date"), a.name or extra.get("name"),
                  a.plan or extra.get("plan", ""), a.look or extra.get("look", ""))


if __name__ == "__main__":
    main()
