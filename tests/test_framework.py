"""No-GPU, no-network tests for the framework layer: CLI, workspace scaffolding, HTML report, narration text,
team-label mapping, momentum run detection and report clips."""
import json
import shutil
from pathlib import Path

import pytest

from hoop_tape_miner import cli, clips, game_config, narrate, new_game, render_html, workspace
from hoop_tape_miner.build_tracks import team_map
from hoop_tape_miner.momentum import auto_stretches, breaks, find_runs, TEXT

FIXTURE = Path(__file__).parent / "fixtures" / "report_min"


def test_cli_lists_all_stages(capsys):
    with pytest.raises(SystemExit) as e:
        cli.main(["--help"])
    assert e.value.code == 0
    out = capsys.readouterr().out
    for stage in ("new-game", "extract", "embed", "recalib", "tracks", "jersey", "analyze", "review", "report",
                  "official", "replay", "html", "narrate", "merge-reviews", "coach-summary", "momentum",
                  "coach-sheets", "plusminus", "calibrate", "clips", "film"):
        assert stage in cli.STAGES
        assert f"  {stage} " in out


def test_cli_unknown_stage_exits_nonzero(capsys):
    with pytest.raises(SystemExit) as e:
        cli.main(["no-such-stage"])
    assert e.value.code == 1
    assert "unknown stage" in capsys.readouterr().out


def test_slug():
    assert workspace.slug("  Red  Foxes ") == "red-foxes"
    assert workspace.slug("Night Owls") == "night-owls"


def test_new_game_scaffolds_workspace(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HOOP_WORKSPACE", str(tmp_path / "ws"))
    video = tmp_path / "game.mp4"
    video.write_bytes(b"")
    cli.main(["new-game", "--opponent", "Red Foxes", "--date", "2026-10-14", "--video", str(video),
              "--us-team", "Example Owls"])
    folder = tmp_path / "ws" / "teams" / "red-foxes" / "2026-10-14"
    assert (folder / "run").is_dir()
    game = json.loads((folder / "game.json").read_text(encoding="utf8"))
    assert game["them"]["team"] == "Red Foxes"
    assert game["us"]["team"] == "Example Owls"
    assert Path(game["video"]) == video.resolve()
    assert "_comment" in game and game["periods"] == []
    dossier = (folder.parent / "README.md").read_text(encoding="utf8")
    assert "Red Foxes" in dossier and "{opponent}" not in dossier
    assert "Next steps" in capsys.readouterr().out
    # a second run keeps the user's edits
    game["periods"] = [[0, 100]]
    (folder / "game.json").write_text(json.dumps(game), encoding="utf8")
    new_game.main(["--opponent", "Red Foxes", "--date", "2026-10-14"])
    assert json.loads((folder / "game.json").read_text(encoding="utf8"))["periods"] == [[0, 100]]


def test_new_game_rejects_bad_date(tmp_path, monkeypatch):
    monkeypatch.setenv("HOOP_WORKSPACE", str(tmp_path))
    with pytest.raises(SystemExit):
        new_game.main(["--opponent", "X", "--date", "14/10/2026"])


def test_render_html_bilingual_page_from_fixture(tmp_path):
    out = tmp_path / "page.html"
    render_html.main([str(FIXTURE), "--out", str(out)])
    page = out.read_text(encoding="utf8")
    assert "Example Owls" in page and "Sample Foxes" in page
    assert "--us: #d1495b;" in page and "--them: #00798c;" in page  # colours from game.json hex
    assert 'data-lang="zh"' in page and 'data-lang="en"' in page
    assert 'id="en-s1"' in page and 'id="zh-s2"' in page
    assert "<b>10–9</b>" in page and "<b>11–9</b>" in page and "<b>21–18</b>" in page
    assert 'class="no-js"' in page  # no-js fallback stays
    assert "<audio" not in page  # no listen.*.mp3 in the fixture
    assert not (FIXTURE / "index.html").exists()


def test_render_html_share_mode_drops_local_links():
    page = render_html.page(FIXTURE, share=True)
    assert "notes/part1.md" not in page
    assert "Keep this item" in page and "nested items stay too" in page


def test_render_html_tolerates_missing_result_and_colours(tmp_path):
    folder = tmp_path / "game"
    shutil.copytree(FIXTURE, folder)
    game = json.loads((folder / "game.json").read_text(encoding="utf8"))
    game.pop("result")
    game["us"].pop("hex")
    (folder / "game.json").write_text(json.dumps(game), encoding="utf8")
    page = render_html.page(folder)
    assert f"--us: {render_html.DEFAULT_COLOURS['us'][0]};" in page
    assert 'data-result="unknown"' in page


def clip_fixture(tmp_path, cut=True):
    folder = tmp_path / "game"
    shutil.copytree(FIXTURE, folder)
    for name, cap in (("README.md", "4 号上篮"), ("README.en.md", "#4 layup")):
        p = folder / name
        p.write_text(p.read_text(encoding="utf8") + f"\n![{cap}](clip:07:24-07:33)\n\n- [▶](#clip-0724-0733)\n",
                     encoding="utf8")
    if cut:
        (folder / "clips").mkdir()
        (folder / "clips" / "0724-0733.mp4").write_bytes(b"fake mp4")
        (folder / "clips" / "0724-0733.jpg").write_bytes(b"fake jpg")
    return folder


def test_clip_markers_and_names(tmp_path):
    assert clips.clip_name("07:24", "07:33") == "0724-0733"
    assert clips.clip_name("1:02.5", "1:10") == "0102_5-0110"
    assert clips.seconds("1:02.5") == 62.5
    assert clips.find_clips(clip_fixture(tmp_path, cut=False)) == [("07:24", "07:33")]  # zh + en share one file


def test_render_html_clip_players(tmp_path):
    folder = clip_fixture(tmp_path)
    page = render_html.page(folder)
    assert page.count("<video") == 2 and 'src="clips/0724-0733.mp4"' in page and 'poster="clips/0724-0733.jpg"' in page
    assert "片段 1 · 07:24–07:33" in page and "Clip 1 · 07:24–07:33" in page
    assert 'id="zh-clip-0724-0733"' in page and 'href="#en-clip-0724-0733"' in page
    shared = render_html.page(folder, share=True)
    assert "data:video/mp4;base64," in shared and "clips/0724-0733" not in shared
    assert 'href="#zh-clip-0724-0733"' in shared  # in-page clip links survive --share


def test_render_html_flags_missing_clip(tmp_path):
    page = render_html.page(clip_fixture(tmp_path, cut=False))
    assert 'class="clip missing"' in page and "<video" not in page


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="needs ffmpeg")
def test_clips_stage_cuts_window(tmp_path):
    import subprocess
    video = tmp_path / "game.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=320x240:rate=25:duration=6",
                    "-pix_fmt", "yuv420p", str(video)], check=True)
    folder = tmp_path / "rep"
    folder.mkdir()
    (folder / "README.md").write_text("# r\n\n![x](clip:0:02-0:04)\n", encoding="utf8")
    clips.main([str(folder), "--video", str(video), "--height", "120"])
    out = folder / "clips" / "0002-0004.mp4"
    assert out.exists() and out.with_suffix(".jpg").exists()
    assert abs(render_html.duration_s(out) - 2) < 0.3


def test_narrate_paragraphs_skip_notes_and_join_lines():
    text = "# note for the writer\nFirst line\ncontinues here.\n\n\n  # indented note\nSecond   paragraph.\n"
    assert narrate.paragraphs(text) == ["First line continues here.", "Second paragraph."]


def test_narrate_voices_from_game():
    vt = narrate.voices({"narration": {"voices": {"en": "en-GB-RyanNeural", "zh": {"voice": "zh-X", "rate": "-5%"}}}})
    assert vt["en"] == ("en-GB-RyanNeural", "+0%")
    assert vt["zh"] == ("zh-X", "-5%")
    assert narrate.voices({}) == narrate.VOICES


def test_team_map_accepts_team_labels_and_colour_words():
    assert team_map({"us", "them", "ref", "unk"}, None) == {"us": "us", "them": "them", "ref": "ref"}
    assert team_map({"navy", "teal", "ref", "unk"}, "navy") == {"navy": "us", "teal": "them", "ref": "ref"}
    assert team_map({"navy", "teal", "ref"}, "teal") == {"teal": "us", "navy": "them", "ref": "ref"}
    with pytest.raises(SystemExit):
        team_map({"navy", "teal", "ref"}, None)
    with pytest.raises(SystemExit):
        team_map({"navy", "teal", "ref"}, "red")


def _flow(points):
    """points: list of (t, team, pts) -> official.json score_flow rows."""
    us = them = 0
    rows = []
    for t, team, pts in points:
        us += pts if team == "us" else 0
        them += pts if team == "them" else 0
        rows.append(dict(our_video_t=t, team=team, points=pts, score_us=us, score_them=them))
    return rows


def test_momentum_finds_the_big_run_and_labels_stretches():
    flow = _flow([(10, "us", 2), (20, "them", 2), (30, "us", 2)]          # 4-2 start
                 + [(40 + 10 * i, "them", 2) for i in range(6)]            # their 12-0 run
                 + [(200, "us", 2), (210, "them", 1)])
    assert find_runs(flow) == [(2, 8)]
    stretches, title = auto_stretches(flow, TEXT["en"], end_t=300)
    labels = [s[0] for s in stretches]
    assert labels == ["Start 4–2", "Their 12–0 run", "Finish 2–1"]
    assert stretches[0][1] == 0 and stretches[-1][2] == 300
    assert "their 12–0 run" in title


def test_momentum_breaks_mark_halftime():
    assert breaks([[0, 600], [700, 1300]]) == [(600, 700, True)]
    q = breaks([[0, 10], [12, 20], [25, 30], [31, 40]])
    assert [h for *_, h in q] == [False, True, False]


def test_plots_use_game_sets_colours_and_names():
    from hoop_tape_miner import plots
    game = json.loads((FIXTURE / "game.json").read_text(encoding="utf8"))
    try:
        plots.use_game(game)
        assert plots.TEAM["us"] == "#d1495b"
        assert plots.TEAM_NAME["them"] == "Sample Foxes (opp)"
    finally:
        plots.use_game({})
    assert plots.TEAM == game_config.DEFAULT_HEX
