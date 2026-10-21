"""9:16 reels of one player's plays, for phones: the player's playlist clips (shots, fouls) cut from the game video
with a vertical crop that follows the player, after a short title card.

Crop: the full source height, width = height * 9/16; its centre follows the player's box centre in
run/tracks.pkl, interpolated across gaps, smoothed over SMOOTH_S and kept inside the frame. A clip where the player
is tracked in less than MIN_TRACKED of the window uses a fixed centre crop instead (counted in the log): the crop
never follows a guess.

Reads game.json (video, run), the reviewed trips (film_index playlists) and <run>/tracks.pkl; writes
<report folder>/reels/reel.<n>.<lang>.mp4 (720x1280, 30 fps, H.264 + mono AAC). No page links a reel, so
`publish` never uploads one: they are files for the player to keep or send.

usage: hoop-tape-miner reels workspace/teams/<opponent>/<date>/player-<n> [--lang zh en] [--max 12] [--force]
       hoop-tape-miner reels workspace/teams/<opponent>/<date> --player 17
"""
from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

import numpy as np

from . import game_config as gc
from . import media
from .timefmt import seconds

OUT = (720, 1280)        # output width, height
FPS = 30
STEP = 0.1               # crop path sample step (s), the tracks' own step
SMOOTH_S = 1.0           # moving-average window of the crop centre (s): no jitter from box noise
MIN_TRACKED = 0.3        # share of a clip's samples with the player tracked, below which the crop stays centred
TITLE_S = 2.0
MAX_CLIPS = 12
SUBTITLE = {"zh": "出手与犯规", "en": "Shots and fouls"}  # title card, under the jersey number


def crop_path(df, side: str, number: str, t0: float, t1: float, src_w: int, crop_w: int):
    """(times from t0, crop left x per time, tracked share) for one window. df: track boxes (t, team, number,
    x1, x2 in source pixels); moments where two boxes carry the number are left out as ambiguous."""
    grid = np.arange(0.0, t1 - t0 + 1e-9, STEP)
    centre = (src_w - crop_w) // 2
    s = df[(df["team"] == side) & (df["number"].astype(str) == str(number)) & (df["t"] >= t0) & (df["t"] <= t1)]
    s = s[~s["t"].round(2).duplicated(keep=False)]
    share = min(1.0, len(s) / len(grid)) if len(grid) else 0.0
    if share < MIN_TRACKED:
        return grid, np.full(len(grid), centre, dtype=int), share
    s = s.sort_values("t")
    c = np.interp(grid + t0, s["t"].to_numpy(float), ((s["x1"] + s["x2"]) / 2).to_numpy(float))
    k = max(1, int(round(SMOOTH_S / STEP)))
    padded = np.concatenate([np.full(k // 2, c[0]), c, np.full(k - 1 - k // 2, c[-1])])
    c = np.convolve(padded, np.ones(k) / k, mode="valid")
    x = np.clip(np.round(c - crop_w / 2), 0, src_w - crop_w).astype(int)
    return grid, x, share


def sendcmd_text(times, xs) -> str:
    """ffmpeg sendcmd lines that move the crop: one per change of x."""
    out, last = [], None
    for t, x in zip(times, xs):
        if x != last:
            out.append(f"{t:.2f} crop x {int(x)};")
            last = x
    return "\n".join(out) + "\n"


def _enc() -> list:
    return ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p", "-r", str(FPS),
            "-c:a", "aac", "-b:a", "96k", "-ac", "1", "-ar", "44100"]


def cut_vertical(video: Path, t0: float, t1: float, xs_cmd: str, x0: int, crop_w: int, src_h: int, out: Path,
                 workdir: Path, size=OUT, audio: bool = True) -> None:
    """One window of the video, cropped to crop_w x src_h with the crop's x moved by the sendcmd text, scaled."""
    cmd = workdir / f"{out.stem}.cmd"
    cmd.write_text(xs_cmd, encoding="utf8")
    vf = (f"sendcmd=f={cmd.name},crop=w={crop_w}:h={src_h}:x={x0}:y=0,scale={size[0]}:{size[1]},setsar=1,"
          f"fps={FPS},format=yuv420p")
    args = ["-ss", f"{t0:.2f}", "-t", f"{t1 - t0:.2f}", "-i", Path(video).resolve()]
    if not audio:
        args += ["-f", "lavfi", "-t", f"{t1 - t0:.2f}", "-i", "anullsrc=r=44100:cl=mono"]
    args += ["-map", "0:v:0", "-map", "0:a:0" if audio else "1:a:0", "-vf", vf, *_enc(), out.resolve()]
    media.ffmpeg(*args, cwd=workdir)  # relative cmd file name: a Windows drive colon breaks filter arguments


def title_card(lines: list[str], out: Path, workdir: Path, accent: str, size=OUT, length: float = TITLE_S) -> None:
    """A dark card with the lines centred (ASS, so CJK text renders), silent audio."""
    from .film import FONT, ass_doc, ass_escape

    w, h = size
    ass = workdir / f"{out.stem}.ass"
    text = "\\N".join(ass_escape(x) for x in lines)
    ass.write_text(ass_doc(w, h, FONT, accent, [(0, length, "Title", text)]), encoding="utf8")
    media.ffmpeg("-f", "lavfi", "-i", f"color=c=0x101010:s={w}x{h}:r={FPS}:d={length:.2f}",
                 "-f", "lavfi", "-t", f"{length:.2f}", "-i", "anullsrc=r=44100:cl=mono",
                 "-vf", f"ass={ass.name},format=yuv420p", *_enc(), out.resolve(), cwd=workdir)


def player_events(folder: Path, number: str) -> tuple[list, dict]:
    """(events with a clip window, video order, each window once; {lang: title lines}) for the player."""
    from .film_index import focus_of, index

    ix = index(folder)
    if not ix:
        return [], {}
    keys = ("p-shots", "p-fouls") if focus_of(folder) else (f"p{number}",)
    lists = [p for p in ix["playlists"] if p.key in keys]
    seen, evs = set(), []
    for e in sorted((e for p in lists for e in p.items), key=lambda e: e.t or 0):
        if e.window not in seen:
            seen.add(e.window)
            evs.append(e)
    return evs, {c: [f"#{number}", sub] for c, sub in SUBTITLE.items()}


def build(folder: Path, number: str, video: Path, df, langs, max_clips: int = MAX_CLIPS, force: bool = False,
          size=OUT, accent: str = "#d1495b") -> dict:
    """Write reels/reel.<number>.<lang>.mp4 for each lang; returns {"clips", "followed", "centred", "out": [paths]}."""
    evs, titles = player_events(folder, number)
    evs = [e for e in evs if e.window][:max_clips]
    res = {"clips": len(evs), "followed": 0, "centred": 0, "out": []}
    if not evs:
        return res
    outs = {c: folder / "reels" / f"reel.{number}.{c}.mp4" for c in langs}
    if all(p.exists() for p in outs.values()) and not force:
        res["out"] = list(outs.values())
        return res
    src_w, src_h = media.video_size(video)
    crop_w = min(src_w, int(round(src_h * 9 / 16 / 2)) * 2)
    audio = media.has_audio(video)
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        parts = []
        for i, e in enumerate(evs):
            t0, t1 = seconds(e.window[0]), seconds(e.window[1])
            times, xs, share = crop_path(df, "us", number, t0, t1, src_w, crop_w)
            res["followed" if share >= MIN_TRACKED else "centred"] += 1
            part = tmp / f"c{i:03d}.mp4"
            cut_vertical(video, t0, t1, sendcmd_text(times, xs), int(xs[0]), crop_w, src_h, part, tmp, size, audio)
            parts.append(part)
        for c, out in outs.items():
            card = tmp / f"title.{c}.mp4"
            title_card(titles.get(c, [f"#{number}"]), card, tmp, accent, size)
            out.parent.mkdir(parents=True, exist_ok=True)
            with media.partial(out) as part:
                media.concat([card] + parts, part, tmp)
            res["out"].append(out)
    return res


def main(argv=None):
    ap = argparse.ArgumentParser(prog="hoop-tape-miner reels", description=__doc__.split("\n\n")[0])
    ap.add_argument("folder", help="player-<n> report folder, or the game folder with --player")
    ap.add_argument("--player", help="jersey number (default: from the player-<n> folder name)")
    ap.add_argument("--lang", nargs="+", default=["zh", "en"], help="title card languages (default zh en)")
    ap.add_argument("--max", type=int, default=MAX_CLIPS, help=f"clips per reel (default {MAX_CLIPS})")
    ap.add_argument("--video", help="the game video (default: game.json video)")
    ap.add_argument("--force", action="store_true", help="rebuild reels that exist")
    a = ap.parse_args(argv)
    from . import film_draw as fd
    from .film_index import focus_of, run_dir

    folder = Path(a.folder)
    number = a.player or focus_of(folder)
    if not number:
        sys.exit("which player? pass a player-<n> folder or --player N")
    game = gc.load_game(folder)
    video = Path(a.video or game.get("video") or "")
    if not video.is_file():
        sys.exit(f"video not found: {str(video) or '(none)'}; pass --video or set game.json video")
    run = run_dir(folder)
    if run is None or not (run / "tracks.pkl").exists():
        sys.exit(f"no tracks.pkl for {folder} (game.json run)")
    df = fd.Tracks.load(run, 1, 1).df
    res = build(folder, str(number), video, df, a.lang, a.max, a.force, accent=gc.team_hex(game, "us"))
    if not res["clips"]:
        print(f"no reviewed clips for #{number} in {folder}; nothing to cut")
        return
    print(f"reel #{number}: {res['clips']} clips ({res['followed']} follow the player, {res['centred']} centre crop)")
    for p in res["out"]:
        print(f"wrote {p}")


if __name__ == "__main__":
    main()
