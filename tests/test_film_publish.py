"""Explained video (film) output options, and publishing never uploads it."""
import shutil
import subprocess
from pathlib import Path

import pytest

from hoop_tape_miner import film, publish, render_html

FIXTURE = Path(__file__).parent / "fixtures" / "report_min"
HAVE_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


def test_scene_cmd_uses_the_crf_option(tmp_path):
    sc = film.Scene("card", "Why the run happened")
    args = lambda **kw: film.scene_cmd(sc, 3.0, 0, 320, 180, tmp_path, None, False, [], "s.ass", "#5b4bd1", "o.mp4", **kw)
    default = args()
    assert default[default.index("-crf") + 1] == str(film.CRF) == "23"
    small = args(crf=30)
    assert small[small.index("-crf") + 1] == "30"


def test_film_cli_passes_crf_to_build(tmp_path, monkeypatch):
    (tmp_path / "film.en.md").write_text("## Card\nHello.\n", encoding="utf8")
    (tmp_path / "game.json").write_text("{}", encoding="utf8")
    seen = []
    monkeypatch.setattr(film, "build", lambda *a: seen.append(a))
    film.main([str(tmp_path), "--crf", "28"])
    film.main([str(tmp_path)])
    assert seen[0][-1] == 28 and seen[1][-1] == film.CRF


@pytest.mark.skipif(not HAVE_FFMPEG, reason="needs ffmpeg")
def test_poster_grabs_one_frame(tmp_path):
    mp4 = tmp_path / "film.zh.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=320x180:rate=25:duration=0.8",
                    "-pix_fmt", "yuv420p", str(mp4)], check=True)
    jpg = film.poster(mp4, mp4.with_suffix(".jpg"))  # shorter than POSTER_S: takes the middle frame
    assert jpg == tmp_path / "film.zh.jpg" and jpg.read_bytes()[:2] == b"\xff\xd8"


def test_publish_never_copies_the_explained_video(tmp_path, monkeypatch):
    folder = tmp_path / "game"
    shutil.copytree(FIXTURE, folder)
    for c in ("zh", "en"):
        (folder / f"film.{c}.mp4").write_bytes(b"fake mp4")
        (folder / f"film.{c}.jpg").write_bytes(b"fake jpg")
        (folder / f"listen.{c}.mp3").write_bytes(b"fake mp3")
    monkeypatch.setattr(render_html, "duration_s", lambda p: 60.0)
    dest = tmp_path / "site" / "tok"
    publish.build_report(folder, dest)
    built = {p.name for p in dest.rglob("*")}
    assert "listen.zh.mp3" in built and not any(n.startswith("film.") for n in built)
    assert "film." not in (dest / "index.html").read_text(encoding="utf8")
