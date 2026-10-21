"""Telestration on clip posters: the players a clip is about get a ring at their feet (the rest of the frame is
dimmed), and a foul gets an arrow from the fouler to the player fouled, so a reader sees who to watch before
pressing play. Drawing reuses film_draw.py (the film stage's freeze frames).

Who is marked, per clip:
    - players named in the clip's caption (`![我#17 drives, 对#25 helps](clip:07:24-07:33)`); a bare `#17` is
      our #17 when the tracks see one at that moment, else theirs;
    - for shot chart / playlist clips, the shooter, the player who lost the ball, or the fouler (-> fouled).
A player is drawn only where run/tracks.pkl has their box at the poster's moment (within 0.25 s); a poster with
nobody found stays plain. Nothing is guessed.

Reads clips/<from>-<to>.jpg, README.md / README.en.md, the reviewed trips and <run>/tracks.pkl; writes
clips/<from>-<to>.mark.jpg. Pages show the marked poster when it is at least as new as the plain one
(clips.poster_of), so re-cut clips fall back to the plain poster until this stage runs again.

usage: hoop-tape-miner posters workspace/teams/<opponent>/<date>[/player-<n>] [--video game.mp4] [--force]
--video (default game.json video) only gives the source frame size the track boxes are measured in.
"""
from __future__ import annotations

import argparse
import re
import sys
import tempfile
from pathlib import Path

from . import film_draw as fd
from . import game_config as gc
from . import media
from .clips import READMES, clip_name

CAPTION_RE = re.compile(r"!\[([^\]]*)\]\(clip:(\d{1,2}:\d{2}(?:\.\d)?)-(\d{1,2}:\d{2}(?:\.\d)?)\)")
REF_RE = re.compile(r"(?<![A-Za-z0-9])(我|us|对|them)?#(\d{1,2})(?!\d)")
STEM_RE = re.compile(r"^(\d{3,})(?:_(\d))?-\d{3,}(?:_\d)?$")
MAX_PLAYERS = 3  # rings per poster: more than that and nobody stands out


def stem_t0(stem: str) -> float | None:
    """'0724-0733' -> 444.0 (video seconds of the clip's first frame, where the poster comes from); None if the
    name is not a clip window."""
    m = STEM_RE.match(stem)
    if not m:
        return None
    digits = m[1]
    return int(digits[:-2]) * 60 + int(digits[-2:]) + (int(m[2]) / 10 if m[2] else 0.0)


def caption_marks(caption: str) -> list[tuple]:
    """Players named in a caption: [('player', 'us'|'them'|None, '17'), ...]; None = bare #17, side unknown."""
    out = []
    for side, num in REF_RE.findall(caption):
        mk = ("player", {"我": "us", "us": "us", "对": "them", "them": "them"}.get(side), num)
        if mk not in out:
            out.append(mk)
    return out


def event_marks(e) -> list[tuple]:
    """Marks for a film_index Event: the shooter / ball loser / fouler, and an arrow fouler -> fouled."""
    if not e.player:
        return []
    me = ("player", e.team, e.player)
    if e.kind == "foul" and e.on:
        other = ("player", "them" if e.team == "us" else "us", e.on)
        return [me, other, ("arrow", me, other)]
    return [me]


def clip_marks(folder: Path) -> dict[str, list[tuple]]:
    """{clip stem: marks} for the folder: caption names first, then the reviewed event the clip was cut for."""
    out: dict[str, list[tuple]] = {}
    for name in READMES:
        p = folder / name
        if p.exists():
            for m in CAPTION_RE.finditer(p.read_text(encoding="utf8")):
                marks = out.setdefault(clip_name(m[2], m[3]), [])
                marks += [mk for mk in caption_marks(m[1]) if mk not in marks]
    from .film_index import index  # film_index imports clips; keep this module light to import
    try:
        ix = index(folder)
    except (OSError, ValueError, KeyError) as ex:
        print(f"warning: no reviewed events for {folder} ({ex})")
        ix = None
    if ix:
        for e in ix["shots"] + [e for p in ix["playlists"] for e in p.items]:
            if e.window:
                marks = out.setdefault(clip_name(*e.window), [])
                marks += [mk for mk in event_marks(e) if mk not in marks]
    return out


def resolve(marks: list[tuple], t: float, tracks) -> list[tuple]:
    """Give bare #N a side (ours if the tracks see our #N at t, else theirs), keep only players the tracks see at t
    (at most MAX_PLAYERS), and arrows whose two ends are both kept."""
    def side_of(mk):
        if mk[1] is not None:
            return mk if tracks.box(mk[1], mk[2], t) else None
        for side in ("us", "them"):
            if tracks.box(side, mk[2], t):
                return ("player", side, mk[2])
        return None

    seen: dict = {}

    def get(mk):
        if mk not in seen:
            seen[mk] = side_of(mk)
        return seen[mk]

    found = []
    for mk in marks:
        if mk[0] == "player":
            r = get(mk)
            if r and r not in found and len(found) < MAX_PLAYERS:
                found.append(r)
    arrows = []
    for mk in marks:
        if mk[0] == "arrow":
            a, b = get(mk[1]), get(mk[2])
            if a in found and b in found:
                arrows.append(("arrow", a, b))
    return found + arrows


def draw(jpg: Path, marks: list[tuple], t: float, tracks, out: Path) -> None:
    """Draw the marks (frame fractions from the tracks at t) onto the poster image -> out (JPEG)."""
    from .film import FONT, ass_doc

    w, h = media.video_size(jpg)
    events = fd.freeze_events(marks, "", t, tracks, w, h, (0, 0, w, h), 0.0, 5.0)
    events = [(s, e, st, txt.replace("\\fad(200,0)", "")) for s, e, st, txt in events]  # a still: no fade-in
    with tempfile.TemporaryDirectory() as tmp, media.partial(out) as part:
        Path(tmp, "marks.ass").write_text(ass_doc(w, h, FONT, fd.MARK_HEX, events), encoding="utf8")
        # relative ass name + cwd: a Windows drive colon would break the filter argument
        media.ffmpeg("-i", Path(jpg).resolve(), "-vf", "ass=marks.ass", "-frames:v", "1", "-update", "1",
                     "-q:v", "4", Path(part).resolve(), cwd=Path(tmp))


def mark_all(folder: Path, tracks, force: bool = False) -> dict:
    """Mark every poster in folder/clips; returns counts {posters, marked, plain, skipped}."""
    marks_by = clip_marks(folder)
    n = {"posters": 0, "marked": 0, "plain": 0, "skipped": 0}
    for jpg in sorted((folder / "clips").glob("*.jpg")):
        if jpg.name.endswith(".mark.jpg"):
            continue
        n["posters"] += 1
        t = stem_t0(jpg.stem)
        out = jpg.with_name(jpg.stem + ".mark.jpg")
        if t is None or not marks_by.get(jpg.stem):
            out.unlink(missing_ok=True)  # nobody to mark any more
            n["plain"] += 1
            continue
        if out.exists() and out.stat().st_mtime >= jpg.stat().st_mtime and not force:
            n["skipped"] += 1
            continue
        marks = resolve(marks_by[jpg.stem], t, tracks)
        if not marks:
            out.unlink(missing_ok=True)  # an older marking no longer holds
            n["plain"] += 1
            continue
        draw(jpg, marks, t, tracks, out)
        n["marked"] += 1
    return n


def main(argv=None):
    ap = argparse.ArgumentParser(prog="hoop-tape-miner posters", description=__doc__.split("\n\n")[0])
    ap.add_argument("folder", help="report folder with clips/ (game folder or player-<n>)")
    ap.add_argument("--video", help="the game video the tracks were measured on (default: game.json video)")
    ap.add_argument("--force", action="store_true", help="redraw posters that are already marked")
    a = ap.parse_args(argv)
    folder = Path(a.folder)
    if not (folder / "clips").is_dir():
        print(f"no clips/ in {folder}; run `hoop-tape-miner clips {folder}` first")
        return
    from .film_index import run_dir

    run = run_dir(folder)
    if run is None or not (run / "tracks.pkl").exists():
        sys.exit(f"no tracks.pkl for {folder} (game.json run); posters stay plain")
    video = Path(a.video or gc.load_game(folder).get("video") or "")
    if not video.is_file():
        sys.exit(f"video not found: {str(video) or '(none)'}; pass --video or set game.json video")
    tracks = fd.Tracks.load(run, *media.video_size(video))
    n = mark_all(folder, tracks, a.force)
    print(f"posters: {n['marked']} marked, {n['skipped']} already marked, {n['plain']} plain of {n['posters']}")


if __name__ == "__main__":
    main()
