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
