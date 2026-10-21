"""pipeline: the step driver shared by run / train / move, its exit protocol and make-style freshness."""
import json
import os
import subprocess
import time
import uuid
from pathlib import Path

import pytest

from hoop_tape_miner import pipeline as P


class Unit(P.Unit):
    JSON = "unit.json"

    @classmethod
    def load(cls, folder: Path) -> "Unit":
        return cls(Path(folder), json.loads((Path(folder) / cls.JSON).read_text(encoding="utf8")), ("zh",))


@pytest.fixture
def unit(tmp_path, monkeypatch):
    monkeypatch.setenv("HOOP_WORKSPACE", str(tmp_path))
    folder = tmp_path / "u"
    (folder / "run").mkdir(parents=True)
    (folder / "unit.json").write_text(json.dumps({"fps": 10}), encoding="utf8")
    (folder / "src.txt").write_text("a", encoding="utf8")
    return folder


class Runner:
    """Stands in for subprocess.run: records stage argv and writes `<stage>.out` in the run folder."""
    def __init__(self, folder: Path, rc: int = 0):
        self.folder, self.rc, self.calls = folder, rc, []

    def __call__(self, cmd, **kw):
        argv = cmd[3:]
        self.calls.append(argv)
        out = self.folder / "run" / f"{argv[0]}.out"
        out.write_text(uuid.uuid4().hex, encoding="utf8")   # new content every run
        return subprocess.CompletedProcess(cmd, self.rc)


def made(name):
    return lambda g: (g.run / f"{name}.out").exists()


def steps():
    """a reads src.txt (fps param); b reads a's output; c depends on a by its run stamp (`after`); d is untracked."""
    return [
        P.Step("a", "cmd", made("a"), lambda g: [["a"]], inputs=lambda g: [g.folder / "src.txt"],
               params=lambda g: {"fps": g.game.get("fps")}, again=("--force",)),
        P.Step("b", "cmd", made("b"), lambda g: [["b"]], inputs=lambda g: [g.run / "a.out"]),
        P.Step("c", "cmd", made("c"), lambda g: [["c"]], inputs=lambda g: [], after=("a",)),
        P.Step("d", "cmd", made("d"), lambda g: [["d"]]),
    ]


def test_first_drive_runs_everything_and_records_tracked_steps(unit):
    r = Runner(unit)
    assert P.drive(Unit.load(unit), steps(), runner=r) == 0
    assert [c[0] for c in r.calls] == ["a", "b", "c", "d"]
    recs = json.loads((unit / P.STORE).read_text(encoding="utf8"))["steps"]
    assert set(recs) == {"a", "b", "c"}
    assert recs["a"]["inputs"] == {"src.txt": P.signature(unit / "src.txt")} and recs["a"]["params"] == {"fps": 10}
    assert set(recs["b"]["inputs"]) == {"run/a.out"} and recs["c"]["after"] == {"a": recs["a"]["run"]}
    r2 = Runner(unit)
    assert P.drive(Unit.load(unit), steps(), runner=r2) == 0 and r2.calls == []


def test_folder_without_records_counts_as_done_and_is_adopted(unit, capsys):
    for n in "abcd":
        (unit / "run" / f"{n}.out").write_text("old", encoding="utf8")
    g = Unit.load(unit)
    assert all(ok for _, _, ok in P.status(g, steps()))
    assert not (unit / P.STORE).exists()                       # --status never writes
    assert P.drive(g, steps(), dry=True, runner=Runner(unit)) == 0
    assert not (unit / P.STORE).exists()                       # nor does --dry
    r = Runner(unit)
    assert P.drive(g, steps(), runner=r) == 0 and r.calls == []
    assert set(json.loads((unit / P.STORE).read_text(encoding="utf8"))["steps"]) == {"a", "b", "c"}


def test_changed_input_makes_the_step_stale_and_its_dependants_follow(unit, capsys):
    P.drive(Unit.load(unit), steps(), runner=Runner(unit))
    (unit / "src.txt").write_text("b", encoding="utf8")
    g = Unit.load(unit)
    rows = {n: (ok, why) for n, _, ok, why in P.rows(g, steps())}
    assert rows["a"] == (False, ["src.txt"]) and rows["b"][0] and rows["d"][0]
    P.print_status(g, steps())
    assert "stale: src.txt" in capsys.readouterr().out
    r = Runner(unit)
    assert P.drive(g, steps(), runner=r) == 0
    assert r.calls == [["a", "--force"], ["b"], ["c"]]         # a over its old output; b (new a.out), c (a ran again)
    assert "changed since its last run: src.txt" in capsys.readouterr().out


def test_same_content_rewritten_is_not_a_change(unit):
    P.drive(Unit.load(unit), steps(), runner=Runner(unit))
    later = time.time() + 30
    os.utime(unit / "src.txt", (later, later))                 # small files are signed by content
    r = Runner(unit)
    assert P.drive(Unit.load(unit), steps(), runner=r) == 0 and r.calls == []


def test_params_change_makes_the_step_stale(unit):
    P.drive(Unit.load(unit), steps(), runner=Runner(unit))
    (unit / "unit.json").write_text(json.dumps({"fps": 15}), encoding="utf8")
    g = Unit.load(unit)
    assert P.changes(steps()[0], g, P.Store(unit)) == ["params"]
    r = Runner(unit)
    P.drive(g, steps(), runner=r)
    assert r.calls[0] == ["a", "--force"]


def test_redo_makes_downstream_steps_stale(unit):
    P.drive(Unit.load(unit), steps(), runner=Runner(unit))
    r = Runner(unit)
    assert P.drive(Unit.load(unit), steps(), redo="a", runner=r) == 0
    assert r.calls == [["a", "--force"], ["b"], ["c"]]          # d tracks nothing: left alone


def test_redo_of_an_adopted_folder_reaches_its_dependants(unit):
    for n in "abcd":
        (unit / "run" / f"{n}.out").write_text("old", encoding="utf8")
    r = Runner(unit)
    assert P.drive(Unit.load(unit), steps(), redo="a", runner=r) == 0
    assert [c[0] for c in r.calls] == ["a", "b", "c"]


def test_until_stops_on_a_stale_step_after_running_it(unit, capsys):
    P.drive(Unit.load(unit), steps(), runner=Runner(unit))
    (unit / "src.txt").write_text("b", encoding="utf8")
    r = Runner(unit)
    assert P.drive(Unit.load(unit), steps(), until="a", runner=r) == 0
    assert r.calls == [["a", "--force"]] and "stopped after a" in capsys.readouterr().out


def test_dry_prints_the_rerun_with_its_extra_args(unit, capsys):
    P.drive(Unit.load(unit), steps(), runner=Runner(unit))
    (unit / "src.txt").write_text("b", encoding="utf8")
    assert P.drive(Unit.load(unit), steps(), dry=True, runner=Runner(unit)) == 0
    assert "[dry] a: hoop-tape-miner a --force" in capsys.readouterr().out


def test_untracked_now_counts_as_fresh(unit):
    s = P.Step("m", "cmd", lambda g: True, lambda g: [["m"]], inputs=lambda g: None)
    store = P.Store(unit)
    assert not P.record(s, Unit.load(unit), store) and P.changes(s, Unit.load(unit), store) == []


def test_unreadable_store_counts_as_empty(unit):
    (unit / P.STORE).write_text("{not json", encoding="utf8")
    assert P.Store(unit).steps == {}


def test_input_keys_survive_moving_the_folder(unit, tmp_path):
    g = Unit.load(unit)
    assert P.input_key(g, unit / "src.txt") == "src.txt"
    assert P.input_key(g, unit / "run" / "x.pkl") == "run/x.pkl"
    assert P.input_key(g, tmp_path / "video.mp4") == "ext/video.mp4"


def test_large_files_are_signed_by_size_and_mtime(tmp_path, monkeypatch):
    monkeypatch.setattr(P, "SMALL", 4)
    p = tmp_path / "big.bin"
    p.write_bytes(b"0123456789")
    sig = P.signature(p)
    assert sig.startswith("10:")
    os.utime(p, (time.time() + 30, time.time() + 30))
    assert P.signature(p) != sig and P.signature(tmp_path / "nope") == "missing"


def test_agent_step_waits_with_exit_3_and_fills_its_instructions(unit, capsys):
    s = [P.Step("ask", "agent", lambda g: False, how="look in {run}", errors=lambda g: [f"e{i}" for i in range(14)])]
    assert P.drive(Unit.load(unit), s, runner=Runner(unit)) == P.WAITING
    out = capsys.readouterr().out
    assert "waiting for the agent: ask" in out and str(unit / "run") in out and "... 2 more" in out


def test_failed_long_step_exits_1_with_its_log_tail(unit, capsys):
    s = [P.Step("a", "cmd", made("a"), lambda g: [["a"]], long=True)]
    assert P.drive(Unit.load(unit), s, runner=Runner(unit, rc=2)) == 1
    out = capsys.readouterr().out
    assert "a failed (exit 2)" in out and "last lines of" in out


def test_failed_step_writes_no_record(unit):
    s = steps()[:1]
    assert P.drive(Unit.load(unit), s, runner=Runner(unit, rc=1)) == 1
    assert not (unit / P.STORE).exists()


def test_publish_runs_only_with_publish(unit, capsys):
    s = [P.Step("publish", "cmd", lambda g: False, lambda g: [["publish"]])]
    r = Runner(unit)
    assert P.drive(Unit.load(unit), s, runner=r) == 0 and r.calls == []
    assert "publish skipped" in capsys.readouterr().out
    assert P.drive(Unit.load(unit), s, publish=True, runner=r) == 0 and r.calls == [["publish"]]


def test_newer_tolerates_files_copied_together(tmp_path):
    out, inp = tmp_path / "out", tmp_path / "in"
    out.write_text("o")
    inp.write_text("i")
    t = out.stat().st_mtime
    os.utime(inp, (t + 1, t + 1))
    assert P.newer(out, inp)
    os.utime(inp, (t + 10, t + 10))
    assert not P.newer(out, inp)
    assert not P.newer(tmp_path / "missing", inp)


# ---- the drivers' step tables ---------------------------------------------------------------------------------

@pytest.fixture
def game(tmp_path, monkeypatch):
    monkeypatch.setenv("HOOP_WORKSPACE", str(tmp_path))
    folder = tmp_path / "teams" / "red-foxes" / "2026-10-14"
    (folder / "run").mkdir(parents=True)
    video = tmp_path / "game.mp4"
    video.write_bytes(b"v1")
    g = {"video": str(video), "periods": [[0, 1000]], "us": {"team": "Night Owls", "focus_player": "17"},
         "them": {"team": "Red Foxes"}, "rosters": {"us": [], "them": []}}
    (folder / "game.json").write_text(json.dumps(g), encoding="utf8")
    for f in ("detections.pkl", "embeddings.npz", "cluster_names.json", "camera.npz", "tracks.pkl", "jersey.json",
              "possessions.pkl", "possession_metrics.pkl"):
        (folder / "run" / f).write_text(f, encoding="utf8")
    return folder


class StageRunner:
    """subprocess.run stand-in that only records the stage argv."""
    def __init__(self):
        self.calls = []

    def __call__(self, cmd, **kw):
        self.calls.append(cmd[3:])
        return subprocess.CompletedProcess(cmd, 0)


def game_steps(*names):
    from hoop_tape_miner import run as R
    return [s for s in R.STEPS if s.name in names]


def test_game_redo_tracks_reruns_the_steps_after_it(game):
    from hoop_tape_miner import run as R
    steps = game_steps("tracks", "jersey", "analyze")
    r = StageRunner()
    assert R.drive(R.Game.load(game), redo="tracks", runner=r, steps=steps) == 0
    assert [c[0] for c in r.calls] == ["tracks", "jersey", "analyze"]
    r = StageRunner()
    assert R.drive(R.Game.load(game), runner=r, steps=steps) == 0 and r.calls == []


def test_game_new_periods_rerun_analyze(game):
    from hoop_tape_miner import run as R
    steps = game_steps("tracks", "jersey", "analyze")
    R.drive(R.Game.load(game), runner=StageRunner(), steps=steps)              # adopts the old run
    g = json.loads((game / "game.json").read_text(encoding="utf8"))
    (game / "game.json").write_text(json.dumps(dict(g, periods=[[5, 1000]])), encoding="utf8")
    assert not {n: ok for n, _, ok in R.status(R.Game.load(game))}["analyze"]
    r = StageRunner()
    R.drive(R.Game.load(game), runner=r, steps=steps)
    assert [c[0] for c in r.calls] == ["analyze"]


def test_game_clips_recut_with_force_when_the_video_changes(game):
    from hoop_tape_miner import run as R
    steps = game_steps("clips")
    R.drive(R.Game.load(game), runner=StageRunner(), steps=steps)
    (game.parents[2] / "game.mp4").write_bytes(b"v2")
    r = StageRunner()
    R.drive(R.Game.load(game), runner=r, steps=steps)
    assert r.calls and all(c[0] == "clips" and c[-1] == "--force" for c in r.calls)


def test_game_status_does_not_write(game, capsys):
    from hoop_tape_miner import run as R
    R.main([str(game), "--status"])
    assert "done  tracks" in capsys.readouterr().out and not (game / P.STORE).exists()


def test_session_tables_share_the_tail_and_train_sheets_is_not_tracked():
    from hoop_tape_miner import move_run, train_run
    tail = ["clips", "listen-script", "narrate", "html", "qa", "publish", "film-script", "film"]
    by = {s.name: s for s in train_run.TRAIN_STEPS}
    assert by["sheets"].inputs is None and by["summary"].inputs and by["scan"].inputs
    assert train_run.NAMES[-8:] == tail and move_run.NAMES[-8:] == tail
