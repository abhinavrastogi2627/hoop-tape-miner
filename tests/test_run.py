"""run stage: steps resume from their outputs, stop at agent steps, and never publish without --publish."""
import json
import os
import subprocess
import time
from pathlib import Path

import pytest

from hoop_tape_miner import run as R


@pytest.fixture
def game(tmp_path, monkeypatch):
    monkeypatch.setenv("HOOP_WORKSPACE", str(tmp_path))
    folder = tmp_path / "teams" / "red-foxes" / "2026-10-14"
    (folder / "run").mkdir(parents=True)
    video = tmp_path / "game.mp4"
    video.write_bytes(b"x")
    g = {"video": str(video), "periods": [[0, 1000], [1120, 2200]],
         "us": {"team": "Night Owls", "label": "Dark", "focus_player": "17"},
         "them": {"team": "Red Foxes", "label": "Light"}, "rosters": {"us": [], "them": []}}
    (folder / "game.json").write_text(json.dumps(g), encoding="utf8")
    kb = tmp_path / "coach_kb.md"
    kb.write_text("### KB-transition-defence\n", encoding="utf8")
    monkeypatch.setattr(R, "KB", kb)
    return folder


VALID_TRIP = {"schema": 2, "pid": 1, "trip": 1, "t0": 1.0, "t1": 9.0, "offence": "us", "result": "unclear",
              "shot": None, "fts": None, "foul": None, "evidence": {}, "confidence": "low"}


VALID_INSIGHT = {"id": "T1", "kb": ["transition-defence"], "claim": "c", "why": "w", "rule": "r", "drill": "d",
                 "target_next_game": "t", "evidence": [{"t": 2.0, "pid": 1, "trip": 1, "what": "a"},
                                                       {"t": 8.0, "pid": 1, "trip": 1, "what": "b"}],
                 "counter_examples": [], "numbers": {}, "confidence": "low", "critic": None}


def touch(folder: Path, *rel: str):
    """Create placeholder files; coach_part*.json get one valid v2 trip, insights.json one valid insight,
    eval/run.json a passing coach-eval gate."""
    for r in rel:
        p = folder / r
        p.parent.mkdir(parents=True, exist_ok=True)
        body = (json.dumps([VALID_TRIP]) if p.name.startswith("coach_part") else
                json.dumps([VALID_INSIGHT]) if p.name == "insights.json" else
                json.dumps({"facts": {}, "gate": {"pass": True}}) if p.parent.name == "eval" else
                "{}" if p.suffix == ".json" else "x")
        p.write_text(body, encoding="utf8")


def sign_critic(review: Path):
    """What the critic step leaves: a sheet for pid 1 in the manifest, critic.json with a verdict that re-opened it,
    signed with `coach-insights critic`."""
    from hoop_tape_miner.coach_insights import main as insights_main
    (review / "manifest.json").write_text(json.dumps([{"pid": 1, "start": 1.0, "end": 9.0, "sheets": ["p001_0.jpg"]}]),
                                          encoding="utf8")
    (review / "p001_0.jpg").write_bytes(b"jpg")
    (review / "critic.json").write_text(json.dumps({"verdicts": [
        {"id": "T1", "verdict": "keep", "note": "both moments checked", "reopened": ["p001_0.jpg"]}]}), encoding="utf8")
    assert insights_main(["critic", "--review", str(review), "--kb", str(R.KB)]) == 0


class Runner:
    """Stands in for subprocess.run: records stage argv and creates the files a stage would write."""
    def __init__(self, folder: Path, writes=None, rc=0):
        self.folder, self.writes, self.rc, self.calls = folder, writes or {}, rc, []

    def __call__(self, cmd, **kw):
        stage = cmd[3]
        self.calls.append(cmd[3:])
        touch(self.folder, *self.writes.get(stage, []))
        return subprocess.CompletedProcess(cmd, self.rc)


def test_status_lists_every_step_in_order(game):
    names = [n for n, _, _ in R.status(R.Game.load(game))]
    assert names == R.NAMES
    assert names.index("calibrate") < names.index("extract") < names.index("film-review") < names.index("html")
    assert names[-2:] == ["film-script", "film"]


def test_ball_steps_feed_the_sheets(game):
    names = R.NAMES
    assert (names.index("analyze") < names.index("ball-track") < names.index("rim-scan")
            < names.index("shot-proposals") < names.index("coach-sheets"))
    g = R.Game.load(game)
    cmd = R.STEPS[names.index("shot-proposals")].args(g)[0]
    assert cmd[0] == "shot-proposals" and ("--official" in cmd) == g.official.exists()


def test_insights_step_order(game):
    names = R.NAMES
    assert names.index("summary") < names.index("insights") < names.index("critic") < names.index("facts")
    touch(game, "run/review_v1/manifest.json", "run/review_v1/part1.json", "run/review_v1/coach_part1.json",
          "run/review_v1/summary.json")
    g = R.Game.load(game)
    done = {n: ok for n, _, ok in R.status(g)}
    assert done["summary"] and not done["insights"]
    (g.review / "insights.json").write_text(json.dumps([dict(VALID_INSIGHT, kb=["nope"])]), encoding="utf8")
    assert R.insights_errors(g)
    touch(game, "run/review_v1/insights.json")
    assert not R.insights_errors(g)
    how = next(s.how for s in R.STEPS if s.name == "insights")
    assert "coach_insights.md" in how and "--no-critic" in how and "coach_critic.md" not in how


def test_insight_evidence_without_its_trip_fails_the_writer_step(game):
    touch(game, "run/review_v1/coach_part1.json", "run/review_v1/summary.json")
    g = R.Game.load(game)
    no_pid = dict(VALID_INSIGHT, evidence=[{"t": 2.0, "what": "a"}, {"t": 8.0, "what": "b"}])
    (g.review / "insights.json").write_text(json.dumps([no_pid]), encoding="utf8")
    assert any("pid" in e for e in R.insights_errors(g))


def test_critic_is_its_own_step_and_needs_a_signed_critic_json(game, capsys):
    touch(game, "run/review_v1/coach_part1.json", "run/review_v1/summary.json", "run/review_v1/insights.json")
    g = R.Game.load(game)
    step = next(s for s in R.STEPS if s.name == "critic")
    assert step.kind == "agent" and not step.done(g)
    assert "coach_critic.md" in step.how and "coach-insights critic" in step.how
    assert any("critic.json" in e for e in step.errors(g))
    # a verdict set inside insights.json alone (self-certified) does not count
    (g.review / "insights.json").write_text(json.dumps([dict(VALID_INSIGHT, critic={"verdict": "keep", "note": "ok"})]),
                                            encoding="utf8")
    assert not step.done(g)
    touch(game, "run/review_v1/insights.json")
    sign_critic(g.review)
    assert step.done(g)
    items = json.loads((g.review / "insights.json").read_text(encoding="utf8"))
    items[0]["claim"] = "edited after the critic"
    (g.review / "insights.json").write_text(json.dumps(items), encoding="utf8")
    assert not step.done(g)


def test_coach_eval_step_runs_with_the_gate_after_the_film_review(game):
    names = R.NAMES
    assert names.index("features") < names.index("coach-eval") < names.index("summary")
    touch(game, "run/review_v1/coach_part1.json")
    g = R.Game.load(game)
    step = next(s for s in R.STEPS if s.name == "coach-eval")
    assert step.kind == "cmd" and step.done(g)          # no official.json: nothing to compare against
    touch(game, "run/official.json")
    assert not step.done(g)
    argv = step.args(g)[0]
    assert argv[0] == "coach-eval" and "--gate" in argv and argv[argv.index("--label") + 1] == "run"
    ev = g.review / "eval" / "run.json"
    ev.parent.mkdir()
    ev.write_text(json.dumps({"facts": {}, "gate": {"pass": False}}), encoding="utf8")
    assert not step.done(g)
    touch(game, "run/review_v1/eval/run.json")
    assert step.done(g)
    later = time.time() + 30
    os.utime(g.review / "coach_part1.json", (later, later))     # trips changed after the eval
    assert not step.done(g)


def test_status_shows_the_last_eval_and_its_regressions(game, capsys):
    ev = game / "run/review_v1/eval/run.json"
    ev.parent.mkdir(parents=True)
    ev.write_text(json.dumps({"at": "2026-01-01T10:00:00", "previous": "old",
                              "facts": {"us": {"pts_recall": 0.9, "pts_precision": 1.0},
                                        "them": {"pts_recall": 0.85, "pts_precision": 0.9}},
                              "gate": {"pass": True, "failed": [], "skipped": []},
                              "regressions": ["us pts_recall 1.0 -> 0.9"]}), encoding="utf8")
    R.main([str(game), "--status"])
    out = capsys.readouterr().out
    assert "coach-eval" in out and "us pts recall 0.9" in out and "gate PASS" in out
    assert "WARNING" in out and "1.0 -> 0.9" in out


def test_waiting_step_lists_its_errors_and_finished_games_get_the_legacy_note(game, capsys):
    touch(game, "run/calib/keyframes.json", "run/detections.pkl", "run/camera.npz", "run/embeddings.npz",
          "run/cluster_names.json", "run/tracks.pkl", "run/jersey.json", "run/possessions.pkl",
          "run/possession_metrics.pkl", "run/review_v1/manifest.json", "run/review_v1/brief_part1.md")
    (game / "run/review_v1/part1.json").write_text(json.dumps(
        [{"pid": 1, "start": 1.0, "end": 9.0}, {"pid": 2, "start": 20.0, "end": 30.0}]), encoding="utf8")
    touch(game, "run/review_v1/coach_part1.json")
    g = json.loads((game / "game.json").read_text(encoding="utf8"))
    (game / "game.json").write_text(json.dumps(dict(g, no_league_data=True)), encoding="utf8")
    assert R.drive(R.Game.load(game), runner=Runner(game)) == R.WAITING
    out = capsys.readouterr().out
    assert "waiting for the agent: film-review" in out and "pid 2" in out and "no trip" in out
    assert "note:" not in out
    for d in ("", "player-17/"):
        touch(game, d + "README.md", d + "README.en.md")
    R.drive(R.Game.load(game), runner=Runner(game))
    out = capsys.readouterr().out
    assert "note:" in out and "Newly required" in out


def test_review_dir_override(game):
    g = R.Game.load(game)
    assert g.review == g.run / "review_v1"
    g.game["review_dir"] = "review_v3"
    assert g.review == g.run / "review_v3"
    g.game["review_dir"] = str(game / "elsewhere")
    assert g.review == game / "elsewhere"


def test_lineup_falls_back_to_run_folder(game):
    g = R.Game.load(game)
    touch(game, "run/lineup_intervals.json")
    assert g.lineup == g.run / "lineup_intervals.json"
    touch(game, "run/review_v1/lineup_intervals.json")
    assert g.lineup == g.review / "lineup_intervals.json"


def test_features_step_runs_after_film_review(game):
    names = R.NAMES
    assert names.index("film-review") < names.index("features") < names.index("insights")
    g = R.Game.load(game)
    step = next(s for s in R.STEPS if s.name == "features")
    assert step.kind == "cmd" and not step.done(g)
    assert step.args(g)[0][:1] == ["coach-features"] and str(g.review) in step.args(g)[0]
    touch(game, "run/review_v1/features.json")
    assert step.done(g)


def test_first_cmd_writes_grid_then_waits_for_agent_calibration(game, capsys):
    runner = Runner(game, {"calibrate": ["run/calib/grid_250.jpg"]})
    assert R.drive(R.Game.load(game), runner=runner) == R.WAITING
    assert runner.calls[0][:1] == ["calibrate"] and "--grid" in runner.calls[0]
    assert "--times" in runner.calls[0]
    out = capsys.readouterr().out
    assert "waiting for the agent: calibrate" in out and "points.json" in out


def test_calib_times_cover_both_halves(game):
    ts = [int(t) for t in R.calib_times(R.Game.load(game)).split(",")]
    assert len(ts) == 4 and ts[0] < 1000 < 1120 < ts[-1]


def test_long_stage_logs_to_file_and_failure_prints_tail(game, capsys):
    touch(game, "run/calib/keyframes.json")
    runner = Runner(game, rc=1)
    assert R.drive(R.Game.load(game), runner=runner) == 1
    assert runner.calls[0][0] == "extract"
    assert list((game.parents[2] / "logs").glob("*-extract.log"))
    assert "extract failed" in capsys.readouterr().out


def test_montage_stops_on_expected_exit_then_asks_for_cluster_names(game, capsys):
    touch(game, "run/calib/keyframes.json", "run/detections.pkl", "run/camera.npz", "run/embeddings.npz")
    runner = Runner(game, {"tracks": ["run/cluster_montage.jpg"]}, rc=1)
    assert R.drive(R.Game.load(game), runner=runner) == R.WAITING
    assert "cluster_names.json" in capsys.readouterr().out


def test_later_outputs_mark_earlier_steps_done(game):
    touch(game, "run/detections.pkl", "run/camera.npz", "run/tracks.pkl")
    done = {n: ok for n, _, ok in R.status(R.Game.load(game))}
    assert done["calib-grid"] and done["calibrate"] and done["montage"] and done["clusters"]


def test_film_review_waits_until_every_part_has_a_coach_json(game):
    touch(game, "run/review_v1/manifest.json", "run/review_v1/brief_part1.md", "run/review_v1/brief_part2.md",
          "run/review_v1/coach_part1.json")
    g = R.Game.load(game)
    assert not R.parts_done(g)
    touch(game, "run/review_v1/coach_part2.json")
    assert R.parts_done(g)


def test_parts_done_requires_valid(game):
    touch(game, "run/review_v1/manifest.json", "run/review_v1/brief_part1.md")
    bad = dict(VALID_TRIP, result="made2 + FT 1/1 (and-one)")
    (game / "run/review_v1/coach_part1.json").write_text(json.dumps([bad]), encoding="utf8")
    g = R.Game.load(game)
    assert not R.parts_done(g)
    (game / "run/review_v1/coach_part1.json").write_text("[{", encoding="utf8")
    assert not R.parts_done(g)
    touch(game, "run/review_v1/coach_part1.json")
    assert R.parts_done(g)


def finished_until_html(folder: Path):
    touch(folder, "run/calib/keyframes.json", "run/detections.pkl", "run/camera.npz", "run/embeddings.npz",
          "run/cluster_names.json", "run/tracks.pkl", "run/jersey.json", "run/possessions.pkl",
          "run/possession_metrics.pkl", "run/official.json", "run/review_v1/manifest.json",
          "run/review_v1/part1.json", "run/review_v1/coach_part1.json", "run/review_v1/summary.json", "run/review_v1/features.json",
          "run/review_v1/insights.json", "run/review_v1/players_facts.md", "run/review_v1/player17_facts.md",
          "run/review_v1/eval/run.json")
    sign_critic(folder / "run/review_v1")
    for d in ("", "player-17/"):
        touch(folder, *(d + f for f in ("README.md", "README.en.md", "listen.zh.md", "listen.en.md",
                                        "listen.zh.mp3", "listen.en.mp3")))


def qa_pass(folder: Path):
    """What the QA agent writes after the browser check: PASS plus the stamp `run` printed."""
    (folder / "qa.md").write_text(f"PASS: both pages\nchecked: {R.qa_hash(R.Game.load(folder))}\n", encoding="utf8")


def test_publish_needs_the_flag_and_the_film_still_renders(game, capsys):
    finished_until_html(game)
    touch(game, "film.zh.md", "film.en.md")
    runner = Runner(game, {"html": ["index.html", "player-17/index.html"],
                           "film": ["film.zh.mp4", "film.en.mp4"]})
    assert R.drive(R.Game.load(game), runner=runner) == R.WAITING  # html built, QA not done yet
    out = capsys.readouterr().out
    stamp = R.qa_hash(R.Game.load(game))
    assert "waiting for the agent: qa" in out and f"checked: {stamp}" in out
    qa_pass(game)
    assert R.drive(R.Game.load(game), runner=runner) == 0
    stages = [c[0] for c in runner.calls]
    assert "publish" not in stages and stages[-1] == "film"
    out = capsys.readouterr().out
    assert "publish skipped" in out and "film.zh.mp4" in out


def test_qa_pass_is_bound_to_the_checked_files(game):
    finished_until_html(game)
    touch(game, "index.html", "player-17/index.html")
    g = R.Game.load(game)
    (game / "qa.md").write_text("PASS", encoding="utf8")
    assert not R.qa_done(g)  # no stamp: which pages were checked is unknown
    qa_pass(game)
    assert R.qa_done(g)
    (game / "player-17" / "README.en.md").write_text("# edited after QA\n", encoding="utf8")
    assert not R.qa_done(g)  # the page that would ship was never checked
    (game / "qa.md").write_text(f"FAIL: clip 3 is black\nchecked: {R.qa_hash(g)}\n", encoding="utf8")
    assert not R.qa_done(g)


def test_child_stages_run_with_utf8_io(game):
    touch(game, "run/calib/keyframes.json")
    seen = []

    def runner(cmd, **kw):
        seen.append(kw.get("env") or {})
        return subprocess.CompletedProcess(cmd, 1)
    R.drive(R.Game.load(game), runner=runner)
    assert seen and seen[0].get("PYTHONUTF8") == "1" and seen[0].get("PYTHONIOENCODING") == "utf-8"
    assert "PATH" in seen[0] or "Path" in seen[0]  # the rest of the environment is kept


def test_publish_with_flag_deploys_both_pages(game):
    finished_until_html(game)
    touch(game, "index.html", "player-17/index.html")
    qa_pass(game)
    runner = Runner(game)
    R.drive(R.Game.load(game), publish=True, until="publish", runner=runner)
    assert runner.calls[0][0] == "publish" and "--deploy" in runner.calls[0]
    assert str(game / "player-17") in runner.calls[0]


def test_newer_tolerates_files_copied_together(tmp_path):
    a, b = tmp_path / "a.mp3", tmp_path / "a.md"
    a.write_text("x"), b.write_text("x")
    t = time.time()
    os.utime(a, (t, t)), os.utime(b, (t + 0.5, t + 0.5))
    assert R._newer(a, b)
    os.utime(b, (t + 30, t + 30))
    assert not R._newer(a, b)


def test_embed_runs_again_after_a_new_extract(game):
    touch(game, "run/detections.pkl", "run/camera.npz", "run/embeddings.npz")
    assert dict((n, ok) for n, _, ok in R.status(R.Game.load(game)))["embed"]
    t = time.time()
    os.utime(game / "run/detections.pkl", (t + 60, t + 60))
    assert not dict((n, ok) for n, _, ok in R.status(R.Game.load(game)))["embed"]


def test_languages_come_from_the_team_profile(game, tmp_path):
    g = R.Game.load(game)
    assert g.langs == ("zh", "en")                                    # default without a profile
    (tmp_path / "team.json").write_text(json.dumps({"languages": ["en"]}), encoding="utf8")
    g = R.Game.load(game)
    assert g.langs == ("en",)
    touch(game, "README.en.md", "player-17/README.en.md")
    assert R.reports_done(g)                                          # no Chinese README needed
    steps = {s.name: s for s in R.STEPS}
    assert steps["narrate"].args(g)[0][-2:] == ["--lang", "en"]
    assert [c[c.index("--out") + 1].endswith("momentum.en.png") for c in steps["momentum"].args(g)] == [True]
    (tmp_path / "team.json").write_text(json.dumps({"languages": ["en", "fr"]}), encoding="utf8")
    with pytest.raises(SystemExit, match="fr"):
        R.Game.load(game)


def test_official_json_next_to_game_json_is_found(game):
    touch(game, "official.json")
    assert R.Game.load(game).official == game / "official.json"


def test_redo_reruns_a_done_step(game):
    touch(game, "run/calib/grid_1.jpg")
    runner = Runner(game, {"calibrate": ["run/calib/grid_1.jpg"]})
    R.drive(R.Game.load(game), redo="calib-grid", runner=runner)
    assert runner.calls and runner.calls[0][0] == "calibrate"


def test_until_stops_when_the_step_is_already_done(game, capsys):
    touch(game, "run/calib/grid_1.jpg")
    runner = Runner(game)
    assert R.drive(R.Game.load(game), until="calib-grid", runner=runner) == 0
    assert not runner.calls and "stopped after calib-grid" in capsys.readouterr().out


def test_until_stops_in_custom_step_lists(game, capsys):
    """train / move pass their own steps to drive: --until applies there too."""
    steps = [R.Step("a", "cmd", lambda g: True), R.Step("b", "cmd", lambda g: False, lambda g: [["b"]])]
    runner = Runner(game)
    assert R.drive(R.Game.load(game), until="a", runner=runner, steps=steps) == 0
    assert not runner.calls


def test_url_target_is_fetched_first(game, monkeypatch):
    import sys
    import types
    seen = []
    fake = types.SimpleNamespace(main=lambda argv: seen.append(argv) or game, game_id=lambda url: "abc==")
    monkeypatch.setitem(sys.modules, "hoop_tape_miner.fetch", fake)
    import hoop_tape_miner
    monkeypatch.setattr(hoop_tape_miner, "fetch", fake, raising=False)
    R.main(["https://league.example/game/abc==/overview", "--status"])
    assert seen == [["https://league.example/game/abc==/overview"]]


def test_url_of_a_fetched_game_reuses_its_folder(game, monkeypatch, capsys):
    """Re-entering the run loop with the league url must not fetch again (it would rewrite official.json)."""
    g = json.loads((game / "game.json").read_text(encoding="utf8"))
    g["league"] = {"kind": "glory", "game_id": "abc==", "url": "https://league.example/game/abc==/overview"}
    (game / "game.json").write_text(json.dumps(g), encoding="utf8")
    import sys
    import types
    seen = []
    fake = types.SimpleNamespace(main=lambda argv: seen.append(argv) or game, game_id=lambda url: "abc==")
    monkeypatch.setitem(sys.modules, "hoop_tape_miner.fetch", fake)
    import hoop_tape_miner
    monkeypatch.setattr(hoop_tape_miner, "fetch", fake, raising=False)
    R.main(["https://league.example/game/abc==/overview", "--status"])
    assert seen == [] and "already fetched" in capsys.readouterr().out
    R.main(["https://league.example/game/abc==/overview", "--status", "--refetch"])
    assert seen == [["https://league.example/game/abc==/overview"]]


def test_league_periods_wait_for_the_agent_check(game, capsys):
    g = json.loads((game / "game.json").read_text(encoding="utf8"))
    g["periods_checked"] = False
    (game / "game.json").write_text(json.dumps(g), encoding="utf8")
    runner = Runner(game)
    assert R.drive(R.Game.load(game), runner=runner) == R.WAITING
    assert not runner.calls and "waiting for the agent: periods" in capsys.readouterr().out
