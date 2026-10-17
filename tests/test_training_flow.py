"""Personal training sessions end to end without models or video: summary, page band, publish, the train driver."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from hoop_tape_miner import publish, render_html, train_run, train_summary
from hoop_tape_miner import run as R


def write(p: Path, data):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(data if isinstance(data, str) else json.dumps(data), encoding="utf8")


def rep(i, t, category, result, **kw):
    return dict(id=f"R{i:03d}", t=t, category=category, result=result, **kw)


@pytest.fixture
def session(tmp_path, monkeypatch):
    """Player 17: an earlier session at 40%, and today's: 2/4 free throws, 1/2 left layups, 1 unclear jumper."""
    monkeypatch.setenv("HOOP_WORKSPACE", str(tmp_path))
    root = tmp_path / "players" / "17" / "training"
    old = root / "2026-10-13"
    write(old / "session.json", {"kind": "training", "player": "17", "date": "2026-10-13"})
    write(old / "summary.json", {"session": "2026-10-13", "date": "2026-10-13",
                                 "totals": {"all": {"made": 2, "att": 5, "pct": 0.4, "unclear": 0},
                                            "shot": {"made": 2, "att": 5, "pct": 0.4, "unclear": 0}}})
    folder = root / "2026-10-17"
    video = tmp_path / "media" / "session.mp4"
    video.parent.mkdir(parents=True)
    video.write_bytes(b"x")
    write(folder / "session.json", {
        "kind": "training", "player": "17", "name": "Alex", "date": "2026-10-17", "video": str(video),
        "targets": [{"name": "ft 50%", "match": {"zone": "ft"}, "attempts": 4, "pct": 0.5},
                    {"name": "left layups", "match": {"type": "layup-left"}, "attempts": 5},
                    {"name": "threes", "match": {"zone": "three"}, "attempts": 10}]})
    run = folder / "run"
    write(run / "reps.json", [{"id": f"R{i:03d}", "t": 10.0 * i, "lift": 1.0, "knee_bend": 20.0 + i} for i in range(1, 9)])
    write(run / "dribble.json", [{"from": 100.0, "to": 130.0, "bounces": {"R": 40, "L": 20}, "rate": 2.0, "ball_seen": 0.6}])
    write(run / "activity.json", {"duration_s": 200.0, "active_s": 120.0, "visible_s": 190.0})
    ft = dict(zone="ft", spot="free-throw line", type="ft", hand="R")
    write(run / "train_review" / "review_part1.json", {
        "reps": [rep(1, "00:10", "shot", "make", **ft), rep(2, "00:20", "shot", "miss", miss="short", **ft),
                 rep(3, "00:30", "shot", "make", **ft), rep(4, "00:40", "shot", "miss", miss="left", **ft),
                 rep(5, "00:50", "finish", "make", zone="rim", type="layup-left", hand="L"),
                 rep(6, "01:00", "finish", "miss", zone="rim", type="layup-left", hand="L", miss="rim-out"),
                 rep(7, "01:10", "shot", "unclear", zone="mid", type="catch-shoot", hand="R"),
                 {"id": "R008", "t": "01:20", "category": "not_a_rep"}],
        "added_reps": [], "dribble": [{"from": "01:40", "to": "02:10", "drill": "pound", "hand": "both", "losses": 1}],
        "blocks": [], "notes": "camera steady"})
    return folder


def summary_of(folder: Path) -> dict:
    s = json.loads((folder / "session.json").read_text(encoding="utf8"))
    return train_summary.summarize(folder, s, folder / "run")


def test_summary_counts_targets_dribbling_and_progress(session):
    sm = summary_of(session)
    assert sm["totals"]["all"] == {"made": 3, "att": 6, "pct": 0.5, "unclear": 1}
    assert sm["totals"]["finish"]["made"] == 1 and sm["left_finish_share"] == 1.0
    assert sm["misses"]["short"] == 1 and sm["misses"]["rim-out"] == 1
    assert [t["status"] for t in sm["targets"]] == ["met", "missed", "not_trained"]
    assert sm["dribble"]["seconds"] == 30 and sm["dribble"]["losses"] == 1 and sm["dribble"]["rate"] == 2.0
    assert sm["review"]["not_reviewed"] == [] and sm["review"]["candidates"] == 8
    assert [p["session"] for p in sm["progress"]] == ["2026-10-13", "2026-10-17"]
    assert sm["previous"]["delta_pct"] == pytest.approx(0.1)
    assert sm["form"]["knee_bend"]["n"] == 5  # pose metrics merged by id into the five shots
    text = train_summary.facts(sm)
    assert "3/6 (50%)" in text and "ft 50%" in text and "None" not in text


def test_page_band_shows_the_session_not_a_score(session):
    write(session / "summary.json", summary_of(session))
    sb = render_html.scoreboard(session)
    assert sb["training"] and sb["us"] == "Alex"
    band = render_html.training_board(sb, lambda k: render_html.UI["en"][k])
    assert "3/6" in band and "Training" in band and "+1 unclear" in band
    assert "Targets met<b>1/3</b>" in band and "+10</b> pp" in band


def test_training_sessions_are_never_listed_on_the_team_hub(tmp_path):
    game = tmp_path / "teams" / "red-foxes" / "2026-10-14"
    sess = tmp_path / "players" / "17" / "training" / "2026-10-17"
    for f in (game, sess):
        write(f / "README.md", "# Report\n")
    write(sess / "session.json", {"kind": "training"})
    reg = {"reports": {"teams/red-foxes/2026-10-14": "a" * 8, "players/17/training/2026-10-17": "b" * 8}}
    publish.write_site(tmp_path / "site", reg, tmp_path)
    hub = (tmp_path / "site" / reg["hub"] / "index.html").read_text(encoding="utf8")
    assert "2026-10-14" in hub and "2026-10-17" not in hub


class Runner:
    """Stands in for subprocess.run: records stage argv and creates the files a stage would write."""
    def __init__(self, folder: Path, writes):
        self.folder, self.writes, self.calls = folder, writes, []

    def __call__(self, cmd, **kw):
        self.calls.append(cmd[3:])
        for rel in self.writes.get(cmd[3], []):
            write(self.folder / rel, "{}")
        return subprocess.CompletedProcess(cmd, 0)


def test_train_driver_scans_then_waits_for_the_rim(session, capsys):
    shutil.rmtree(session / "run")
    runner = Runner(session, {"train-scan": ["run/reps.json"], "train-sheets": ["run/train_review/rim_probe.jpg"]})
    assert R.drive(train_run.Session.load(session), runner=runner, steps=train_run.TRAIN_STEPS) == R.WAITING
    assert [c[0] for c in runner.calls] == ["train-scan", "train-sheets"] and "--probe" in runner.calls[1]
    out = capsys.readouterr().out
    assert "waiting for the agent: rim" in out and "rim_probe.jpg" in out and "rim_checked" in out


def test_train_driver_waits_for_every_review_part(session, capsys):
    s = json.loads((session / "session.json").read_text(encoding="utf8"))
    write(session / "session.json", {**s, "rim": [], "rim_checked": True})
    rv = session / "run" / "train_review"
    write(rv / "manifest.json", {})
    for n in (1, 2):
        write(rv / f"brief_part{n}.md", "brief")
    assert R.drive(train_run.Session.load(session), runner=Runner(session, {}), steps=train_run.TRAIN_STEPS) == R.WAITING
    assert "waiting for the agent: film-review" in capsys.readouterr().out
    write(rv / "review_part2.json", {"reps": []})  # part 1 is in the fixture
    runner = Runner(session, {"train-summary": ["summary.json"]})
    assert R.drive(train_run.Session.load(session), runner=runner, steps=train_run.TRAIN_STEPS) == R.WAITING
    assert runner.calls == [["train-summary", str(session)]]
    assert "waiting for the agent: report" in capsys.readouterr().out
