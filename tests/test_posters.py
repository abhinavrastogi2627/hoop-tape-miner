"""Telestrated clip posters: who gets marked, side resolution from the tracks, and the drawn image (ffmpeg)."""
import os
import shutil

import pandas as pd
import pytest

from hoop_tape_miner import clips, posters
from hoop_tape_miner import film_draw as fd
from hoop_tape_miner.film_index import Event

HAVE_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


def test_stem_t0():
    assert posters.stem_t0("0724-0733") == 444.0
    assert posters.stem_t0("10005_5-10010") == 6005.5
    assert posters.stem_t0("cover") is None


def test_caption_marks():
    got = posters.caption_marks("我#17 drives, them#25 helps, #4 cuts, 我#17 again, bonus#3")
    assert got == [("player", "us", "17"), ("player", "them", "25"), ("player", None, "4")]


def test_event_marks():
    foul = Event("foul", "them", "11", 5.0, 1, ("00:01", "00:07"), on="4")
    me, other = ("player", "them", "11"), ("player", "us", "4")
    assert posters.event_marks(foul) == [me, other, ("arrow", me, other)]
    assert posters.event_marks(Event("shot", "us", None, 5.0, 1, ("00:00", "00:07"))) == []


class FakeTracks:
    def __init__(self, seen):
        self.seen = seen

    def box(self, side, number, t):
        return (0.4, 0.3, 0.5, 0.7) if (side, number) in self.seen else None


def test_resolve_sides_and_drops_unseen():
    tr = FakeTracks({("us", "4"), ("them", "11"), ("them", "7")})
    a, b = ("player", "them", "11"), ("player", "us", "4")
    marks = [("player", None, "4"), ("player", None, "7"), ("player", "us", "9"), a, ("arrow", a, b),
             ("arrow", a, ("player", "us", "9"))]
    got = posters.resolve(marks, 5.0, tr)
    # bare #4 is ours (we have one), bare #7 is theirs, our #9 is not in the tracks: no ring, no arrow to them
    assert got == [("player", "us", "4"), ("player", "them", "7"), a, ("arrow", a, b)]
    assert posters.resolve([("player", None, "30")], 5.0, tr) == []


def test_poster_of_prefers_fresh_mark(tmp_path):
    mp4 = tmp_path / "0001-0005.mp4"
    jpg, mark = tmp_path / "0001-0005.jpg", tmp_path / "0001-0005.mark.jpg"
    jpg.write_bytes(b"j")
    assert clips.poster_of(mp4) == jpg
    mark.write_bytes(b"m")
    os.utime(jpg, (1000, 1000))
    os.utime(mark, (2000, 2000))
    assert clips.poster_of(mp4) == mark
    os.utime(jpg, (3000, 3000))  # clip re-cut after marking: the old marks may not fit the new frame
    assert clips.poster_of(mp4) == jpg


@pytest.mark.skipif(not HAVE_FFMPEG, reason="needs ffmpeg")
def test_mark_all_draws_ring_and_dims(tmp_path):
    from PIL import Image

    from hoop_tape_miner import media

    folder = tmp_path / "game"
    (folder / "clips").mkdir(parents=True)
    (folder / "README.md").write_text("![我#4 drives, #11 helps](clip:00:05-00:09)\n![nobody](clip:00:20-00:25)\n",
                                      encoding="utf8")
    for stem in ("0005-0009", "0020-0025"):
        media.ffmpeg("-f", "lavfi", "-i", "color=c=0x808080:s=320x180", "-frames:v", "1", folder / "clips" / f"{stem}.jpg")
    # source video 640x360; our #4 stands in the middle at t=5, their #11 is not tracked then
    df = pd.DataFrame([dict(t=5.0, team="us", number="4", x1=300, y1=120, x2=340, y2=240),
                       dict(t=9.0, team="them", number="11", x1=100, y1=100, x2=140, y2=220)])
    n = posters.mark_all(folder, fd.Tracks(df, 640, 360))
    assert n == {"posters": 2, "marked": 1, "plain": 1, "skipped": 0}
    mark = folder / "clips" / "0005-0009.mark.jpg"
    assert mark.exists() and not (folder / "clips" / "0020-0025.mark.jpg").exists()
    img = Image.open(mark).convert("RGB")
    assert img.size == (320, 180)
    assert sum(img.getpixel((10, 10))) < 3 * 0x80 - 60  # outside the marked player: dimmed
    assert sum(img.getpixel((160, 90))) >= 3 * 0x80 - 15  # the player's body: cut out of the dimming
    assert clips.poster_of(folder / "clips" / "0005-0009.mp4") == mark
    assert posters.mark_all(folder, fd.Tracks(df, 640, 360))["skipped"] == 1
