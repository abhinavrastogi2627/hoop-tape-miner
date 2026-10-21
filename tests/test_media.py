"""media: one ffmpeg / ffprobe wrapper, atomic writes and partial outputs (subprocess faked, nothing encoded)."""
import json
import subprocess
from pathlib import Path

import pytest

from hoop_tape_miner import clips, media


def fake_run(monkeypatch, stdout="", write=None, rc=0):
    """Replace subprocess.run: record (argv, kwargs); `write` creates the last argv path, as ffmpeg would."""
    calls = []

    def run(cmd, **kw):
        calls.append((cmd, kw))
        if write is not None:
            Path(cmd[-1]).write_bytes(write)
        if rc:
            raise subprocess.CalledProcessError(rc, cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout=stdout)
    monkeypatch.setattr(media.subprocess, "run", run)
    return calls


def test_partial_moves_into_place_only_on_success(tmp_path):
    out = tmp_path / "clips" / "a.mp4"
    out.parent.mkdir()
    with media.partial(out) as part:
        part.write_bytes(b"half")
        assert part.name == "a.mp4" and part.parent != out.parent
        assert not list(out.parent.glob("*.mp4"))  # a glob of finished clips never sees a half one
    assert out.read_bytes() == b"half" and not (out.parent / ".partial").exists()

    with pytest.raises(RuntimeError):
        with media.partial(out) as part:
            part.write_bytes(b"broken")
            raise RuntimeError("ffmpeg died")
    assert out.read_bytes() == b"half"  # the old good file stays
    assert not (out.parent / ".partial").exists()


def test_atomic_writes_leave_no_temp_file(tmp_path):
    p = tmp_path / "x.json"
    media.write_json_atomic(p, {"a": "é"})
    media.write_json_atomic(p, {"a": 2})
    assert json.loads(p.read_text(encoding="utf8")) == {"a": 2}
    media.write_text_atomic(tmp_path / "y.md", "hi\n")
    assert (tmp_path / "y.md").read_text(encoding="utf8") == "hi\n"
    assert sorted(x.name for x in tmp_path.iterdir()) == ["x.json", "y.md"]


def test_binaries_honour_the_environment(tmp_path, monkeypatch):
    monkeypatch.delenv("FFMPEG", raising=False)
    monkeypatch.delenv("FFPROBE", raising=False)
    assert media.ffmpeg_exe() == "ffmpeg" and media.ffprobe_exe() == "ffprobe"
    ff = tmp_path / "ffmpeg.exe"
    ff.write_bytes(b"")
    monkeypatch.setenv("FFMPEG", str(ff))
    assert media.ffprobe_exe() == "ffprobe"  # no ffprobe next to it
    (tmp_path / "ffprobe.exe").write_bytes(b"")
    assert media.ffprobe_exe() == str(tmp_path / "ffprobe.exe")
    monkeypatch.setenv("FFPROBE", "/opt/probe")
    assert media.ffmpeg_exe() == str(ff) and media.ffprobe_exe() == "/opt/probe"


def test_ffmpeg_never_reads_stdin_and_ffprobe_has_a_timeout(tmp_path, monkeypatch):
    monkeypatch.delenv("FFMPEG", raising=False)
    monkeypatch.delenv("FFPROBE", raising=False)
    calls = fake_run(monkeypatch, stdout="12.5\n")
    media.ffmpeg("-i", tmp_path / "a.mp4", "out.mp4", cwd=tmp_path)
    cmd, kw = calls[-1]
    assert cmd[:5] == ["ffmpeg", "-nostdin", "-v", "error", "-y"] and cmd[-1] == "out.mp4"
    assert kw["check"] and kw["cwd"] == tmp_path
    assert media.duration_s(tmp_path / "a.mp3") == 12.5
    cmd, kw = calls[-1]
    assert cmd[0] == "ffprobe" and kw["timeout"] and kw["encoding"] == "utf8" and kw["check"]


def test_concat_list_quotes_apostrophes(tmp_path, monkeypatch):
    calls = fake_run(monkeypatch)
    d = tmp_path / "it's"
    media.concat([d / "p0.mp4", d / "p1.mp4"], tmp_path / "out.mp4", tmp_path)
    listing = (tmp_path / "list.txt").read_text(encoding="utf8")
    assert listing.splitlines()[0] == "file '" + tmp_path.as_posix() + r"/it'\''s/p0.mp4'"
    cmd = calls[-1][0]
    assert "concat" in cmd and "+faststart" in cmd and cmd[-1] == str(tmp_path / "out.mp4")


def test_a_failed_cut_leaves_no_half_clip(tmp_path, monkeypatch):
    fake_run(monkeypatch, write=b"half", rc=1)
    out = tmp_path / "clips" / "a.mp4"
    with pytest.raises(subprocess.CalledProcessError):
        clips.cut(tmp_path / "game.mp4", "00:10", "00:14", out)
    assert not out.exists() and not list(out.parent.rglob("*.mp4"))
