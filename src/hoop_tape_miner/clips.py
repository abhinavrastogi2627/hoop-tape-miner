"""Cut the video clips a report embeds, so readers can watch the play next to the analysis.

A report marks a clip as a markdown image with a `clip:` link in video time (mm:ss of our video):

    ![#17 dribbles alone into #25's press, steal, and-one](clip:07:24-07:33)

This stage scans README.md and README.en.md in the folder, cuts every referenced window from the game video
into `clips/<from>-<to>.mp4` (small H.264, 480p, mono audio) plus a `.jpg` poster, and skips files that already
exist. `hoop-tape-miner html` turns the same markers into players (embedded in --share pages).
It also cuts the short windows the page's shot chart and playlists need (one per reviewed shot, turnover and foul
with a video time, see film_index.py); a window shared by a marker, the chart and a playlist is cut once.

usage: hoop-tape-miner clips workspace/teams/<opponent>/<date> [--video game.mp4] [--height 480] [--force]
       hoop-tape-miner clips workspace/teams/<opponent>/<date>/player-<number> --video game.mp4
--video defaults to game.json "video" (folder or its parent).
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from . import game_config as gc
from . import media
from .timefmt import seconds

READMES = ("README.md", "README.en.md")
CLIP_RE = re.compile(r"\]\(clip:(\d{1,2}:\d{2}(?:\.\d)?)-(\d{1,2}:\d{2}(?:\.\d)?)\)")
LONG_CLIP_S = 45  # longer clips get a warning: they bloat the shared page and nobody watches them to the end


def clip_name(start: str, end: str) -> str:
    """'07:24', '07:33' -> '0724-0733' (file stem; also the anchor `#clip-0724-0733`)."""
    def part(t):
        m, s = t.split(":")
        return f"{int(m):02d}{s.replace('.', '_')}"
    return f"{part(start)}-{part(end)}"


def clip_path(folder: Path, start: str, end: str) -> Path:
    return folder / "clips" / f"{clip_name(start, end)}.mp4"


def poster_of(mp4: Path) -> Path:
    """The poster a page shows for a clip: the telestrated `<stem>.mark.jpg` (posters stage) when it is at least as
    new as the plain first-frame `<stem>.jpg`, else the plain one (which may not exist)."""
    jpg, mark = mp4.with_suffix(".jpg"), mp4.with_name(mp4.stem + ".mark.jpg")
    if mark.exists() and (not jpg.exists() or mark.stat().st_mtime >= jpg.stat().st_mtime):
        return mark
    return jpg


def find_clips(folder: Path, film: bool = True) -> list[tuple[str, str]]:
    """Unique (start, end) windows referenced by the folder's READMEs, in order of first appearance, then (film)
    the shot chart / playlist windows from the reviewed trips."""
    seen = {}
    for name in READMES:
        p = folder / name
        if p.exists():
            for m in CLIP_RE.finditer(p.read_text(encoding="utf8")):
                seen.setdefault(m.groups(), None)
    if film:
        from .film_index import windows  # film_index imports this module
        for w in windows(folder):
            seen.setdefault(w, None)
    return list(seen)


def cut(video: Path, start: str, end: str, out: Path, height: int = 480):
    t0, t1 = seconds(start), seconds(end)
    if t1 <= t0:
        raise ValueError(f"clip {start}-{end}: end must be after start")
    out.parent.mkdir(parents=True, exist_ok=True)
    with media.partial(out) as part:  # a stopped run leaves no half clip that the next run would skip
        media.ffmpeg("-ss", f"{t0:.2f}", "-i", video, "-t", f"{t1 - t0:.2f}",
                     "-vf", f"scale=-2:{height},fps=30", "-c:v", "libx264", "-preset", "veryfast", "-crf", "28",
                     "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-c:a", "aac", "-b:a", "64k", "-ac", "1", part)
        # poster = first frame, so a reader sees which play it is before pressing play (made before the clip
        # lands, so a finished clip always has one)
        media.ffmpeg("-i", part, "-frames:v", "1", "-q:v", "6", out.with_suffix(".jpg"))


def main(argv=None):
    ap = argparse.ArgumentParser(prog="hoop-tape-miner clips", description=__doc__.split("\n\n")[0])
    ap.add_argument("folder", help="report folder with README.md / README.en.md")
    ap.add_argument("--video", help="our game video (default: game.json video)")
    ap.add_argument("--height", type=int, default=480, help="clip height in pixels (default 480)")
    ap.add_argument("--force", action="store_true", help="re-cut clips that already exist")
    a = ap.parse_args(argv)
    folder = Path(a.folder)
    clips = find_clips(folder)
    if not clips:
        print("no clip:mm:ss-mm:ss markers in the READMEs; nothing to cut")
        return
    video = Path(a.video or gc.load_game(folder).get("video") or "")
    if not video.is_file():
        sys.exit(f"video not found: {str(video) or '(none)'}; pass --video or set game.json video")
    for start, end in clips:
        out = clip_path(folder, start, end)
        if seconds(end) - seconds(start) > LONG_CLIP_S:
            print(f"warning: clip {start}-{end} is longer than {LONG_CLIP_S} s; consider a tighter window")
        if out.exists() and not a.force:
            continue
        cut(video, start, end, out, a.height)
        print(f"wrote {out} {out.stat().st_size / 1024:.0f} KB")
    used = {clip_path(folder, s, e).stem for s, e in clips}
    stale = sorted(p.name for p in (folder / "clips").glob("*.mp4") if p.stem not in used)
    if stale:
        print("not referenced any more (delete if unwanted):", ", ".join(stale))
    print(f"{len(clips)} clips in {folder / 'clips'}")


if __name__ == "__main__":
    main()
