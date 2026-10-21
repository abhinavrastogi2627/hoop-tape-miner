"""9:16 reels: the crop path follows the tracked player, falls back to a centre crop, and the cut joins (ffmpeg)."""
import shutil

import numpy as np
import pandas as pd
import pytest

from hoop_tape_miner import reels
from hoop_tape_miner.film_index import Event

HAVE_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


def boxes(fn, t0=0.0, t1=6.0, number="4", team="us"):
    """Box rows every 0.1 s; fn(t) -> centre x (source px) or None when not tracked."""
    rows = []
    for t in np.round(np.arange(t0, t1 + 1e-9, 0.1), 1):
        c = fn(t)
        if c is not None:
            rows.append(dict(t=float(t), team=team, number=number, x1=c - 20, x2=c + 20, y1=100, y2=300))
    return pd.DataFrame(rows)


def test_crop_follows_and_stays_inside():
    df = boxes(lambda t: 100 + 100 * t)  # walks right across a 640 px frame
    times, xs, share = reels.crop_path(df, "us", "4", 1.0, 5.0, 640, 202)
    assert share == 1.0 and times[0] == 0.0
    assert xs[0] < xs[len(xs) // 2] < xs[-1]  # moves right with the player
    assert xs.min() >= 0 and xs.max() <= 640 - 202  # never past the frame edge
    mid = len(xs) // 2
    assert abs(xs[mid] + 101 - (100 + 100 * (1.0 + times[mid]))) < 15  # centred on the player


def test_crop_smooths_a_one_frame_jump():
    df = boxes(lambda t: 1000 if abs(t - 3.0) < 0.05 else 300)
    _, xs, _ = reels.crop_path(df, "us", "4", 1.0, 5.0, 1280, 404)
    assert xs.max() - xs.min() < 100  # one bad box moves the crop a little, not 700 px


def test_crop_centre_when_rarely_tracked():
    df = boxes(lambda t: 500 if t < 1.5 else None)
    times, xs, share = reels.crop_path(df, "us", "4", 1.0, 5.0, 640, 202)
    assert share < reels.MIN_TRACKED and set(xs) == {(640 - 202) // 2}
    both = pd.concat([boxes(lambda t: 100), boxes(lambda t: 500)])  # two boxes carry #4: ambiguous throughout
    assert set(reels.crop_path(both, "us", "4", 1.0, 5.0, 640, 202)[1]) == {(640 - 202) // 2}


def test_sendcmd_text_only_on_change():
    assert reels.sendcmd_text([0.0, 0.1, 0.2, 0.3], [10, 10, 12, 12]) == "0.00 crop x 10;\n0.20 crop x 12;\n"


@pytest.mark.skipif(not HAVE_FFMPEG, reason="needs ffmpeg")
def test_build_reel(tmp_path, monkeypatch):
    from hoop_tape_miner import media

    video = tmp_path / "game.mp4"
    media.ffmpeg("-f", "lavfi", "-i", "testsrc=s=640x360:r=25:d=8", "-f", "lavfi", "-i", "sine=d=8",
                 "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-shortest", video)
    folder = tmp_path / "game" / "player-4"
    folder.mkdir(parents=True)
    evs = [Event("shot", "us", "4", 2.0, 1, ("00:01", "00:03")), Event("foul", "us", "4", 6.0, 1, ("00:05", "00:07"))]
    monkeypatch.setattr(reels, "player_events", lambda f, n: (evs, {"en": ["#4", "Shots and fouls"]}))
    df = boxes(lambda t: 100 + 60 * t, 0, 4)  # tracked in the first window only
    res = reels.build(folder, "4", video, df, ["en"], size=(180, 320))
    out = folder / "reels" / "reel.4.en.mp4"
    assert res["out"] == [out] and res["followed"] == 1 and res["centred"] == 1
    assert media.video_size(out) == (180, 320)
    assert abs(media.duration_s(out) - (reels.TITLE_S + 4.0)) < 0.5
    assert media.has_audio(out)
