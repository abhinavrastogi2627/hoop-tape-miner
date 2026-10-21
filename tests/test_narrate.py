"""narrate: paragraph split and the --tight silence trim (ffmpeg calls recorded, not run)."""
from hoop_tape_miner import narrate as N


def test_paragraphs_drop_writer_notes():
    assert N.paragraphs("# note\nfirst  line\nsame para\n\nsecond") == ["first line same para", "second"]


def record_ffmpeg(monkeypatch):
    calls = []
    monkeypatch.setattr(N, "ffmpeg", lambda *a: calls.append(a))
    return calls


def concat_list(tmp_path):
    return (tmp_path / "list.txt").read_text(encoding="utf8")


def test_stitch_tight_trims_every_part(tmp_path, monkeypatch):
    calls = record_ffmpeg(monkeypatch)
    parts = [tmp_path / "p000.mp3", tmp_path / "p001.mp3"]
    N.stitch(parts, tmp_path / "out.mp3", tmp_path, gap=0.4, tight=True)
    trims = [c for c in calls if "-af" in c and "silenceremove" in c[c.index("-af") + 1]]
    assert len(trims) == 2
    listing = concat_list(tmp_path)
    assert "p000.trim.mp3" in listing and "p001.trim.mp3" in listing
    assert "p000.mp3'" not in listing


def test_stitch_without_tight_keeps_parts(tmp_path, monkeypatch):
    calls = record_ffmpeg(monkeypatch)
    N.stitch([tmp_path / "p000.mp3"], tmp_path / "out.mp3", tmp_path)
    assert not any("silenceremove" in " ".join(c) for c in calls)
    assert ".trim." not in concat_list(tmp_path)


def test_concat_list_quotes_paths_with_an_apostrophe(tmp_path, monkeypatch):
    record_ffmpeg(monkeypatch)
    part = tmp_path / "it's" / "p000.mp3"
    N.stitch([part], tmp_path / "out.mp3", tmp_path)
    assert "file '" + (tmp_path / "it").as_posix() + r"'\''s/p000.mp3'" in concat_list(tmp_path)


def test_ffprobe_has_a_timeout(tmp_path, monkeypatch):
    import subprocess
    from hoop_tape_miner import render_html
    seen = {}

    def fake_run(cmd, **kw):
        seen.update(kw)
        return subprocess.CompletedProcess(cmd, 0, stdout="12.5\n")
    monkeypatch.setattr(render_html.subprocess, "run", fake_run)
    assert render_html.duration_s(tmp_path / "a.mp3") == 12.5
    assert seen.get("timeout") and seen.get("encoding") == "utf8"
