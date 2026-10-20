"""Personal training sessions: pose helpers on synthetic keypoints, review aggregation, targets, stages' glue."""
import json

import numpy as np
import pytest

from hoop_tape_miner import training as T

FPS = 15


def person(t: np.ndarray) -> np.ndarray:
    """A synthetic player standing at x=500: shoulders y=200, hips y=300 (torso 100 px), arms down."""
    kp = np.zeros((len(t), 17, 2))
    pts = {T.NOSE: (500, 160), T.L_SH: (480, 200), T.R_SH: (520, 200), T.L_EL: (475, 250), T.R_EL: (525, 250),
           T.L_WR: (472, 295), T.R_WR: (528, 295), T.L_HIP: (485, 300), T.R_HIP: (515, 300),
           T.L_KN: (485, 380), T.R_KN: (515, 380), T.L_AN: (485, 460), T.R_AN: (515, 460)}
    for k, (x, y) in pts.items():
        kp[:, k] = (x, y)
    return kp


def shoot(kp, t, at, hand=T.R_WR, travel=0.0):
    """Knee dip 0.4 s before `at`, wrist(s) up to 1 torso above the shoulders at `at`; optional run-up in x."""
    for i, ti in enumerate(t):
        d = ti - at
        if -0.6 <= d <= -0.2:  # dip: knees forward
            kp[i, [T.L_KN, T.R_KN], 0] += 40 * (1 - abs(d + 0.4) / 0.2).clip(0)
        if -0.5 <= d <= 0.25:
            up = 1 - abs(d) / 0.5 if d < 0 else 1 - d / 0.25
            kp[i, hand, 1] = 295 - up * 195
            kp[i, hand - 2, 1] = 250 - up * 120  # elbow follows
        if travel and -1.2 <= d <= 0:
            kp[i, :, 0] += travel * (d + 1.2) / 1.2
    return kp


@pytest.fixture
def session_kp():
    t = np.arange(0, 30, 1 / FPS)
    kp = person(t)
    kp = shoot(kp, t, 5.0)
    kp = shoot(kp, t, 10.0, hand=T.L_WR, travel=200)  # left-hand finish after a drive
    for i, ti in enumerate(t):  # right-hand dribble 15-20 s at 2 bounces / s
        if 15 <= ti <= 20:
            kp[i, T.R_WR, 1] = 360 + 40 * np.cos(2 * np.pi * 2 * (ti - 15))
    return t, kp


def test_find_reps_shot_and_finish(session_kp):
    t, kp = session_kp
    reps = T.find_reps(t, kp)
    assert [r["t"] for r in reps] == pytest.approx([5.0, 10.0], abs=0.1)
    shot, fin = reps
    assert (shot["hint"], shot["hand"]) == ("shot", "R")
    assert (fin["hint"], fin["hand"]) == ("finish", "L")
    assert shot["lift"] == pytest.approx(1.0, abs=0.05)
    assert shot["knee_bend"] > 20 and 0.2 < shot["dip_to_release"] < 0.6
    assert shot["elbow_release"] is not None


def test_find_dribbles(session_kp):
    t, kp = session_kp
    d = T.find_dribbles(t, kp)
    assert len(d) == 1
    assert d[0]["from"] == pytest.approx(15, abs=0.6) and d[0]["to"] == pytest.approx(20, abs=0.6)
    assert d[0]["bounces"]["R"] >= 8 and d[0]["bounces"]["L"] == 0
    assert d[0]["rate"] == pytest.approx(2, abs=0.4)
    assert d[0]["ball_seen"] is None


def test_dribbles_checked_against_the_ball(session_kp):
    t, kp = session_kp
    ball = np.full((len(t), 2), np.nan)
    on = (t >= 15) & (t <= 20)
    ball[on] = kp[on, T.R_WR] + (0, 30)  # the ball under the right hand
    d = T.find_dribbles(t, kp, ball=ball)
    assert len(d) == 1 and d[0]["ball_seen"] > 0.8
    # a short rhythm never near the ball (running, arm swing) is dropped; a long one is kept for the reviewer
    no_ball = np.full((len(t), 2), np.nan)
    assert T.find_dribbles(t, kp, ball=no_ball, min_unseen_bounces=50) == []
    assert len(T.find_dribbles(t, kp, ball=no_ball, min_unseen_bounces=4)) == 1

def test_low_confidence_points_are_ignored(session_kp):
    t, kp = session_kp
    conf = np.ones(kp.shape[:2])
    conf[:, T.R_WR] = 0.1  # the right wrist is never seen: no right-hand shot, no dribble
    assert [r["t"] for r in T.find_reps(t, kp, conf)] == pytest.approx([10.0], abs=0.1)
    assert T.find_dribbles(t, kp, conf) == []


def test_pick_main_follows_the_player():
    a, b = np.array([[100, 100, 200, 400]]), np.array([[700, 100, 760, 250]])  # player, small passer-by
    frames = [np.r_[a, b], np.r_[b, a + 10], np.zeros((0, 4)), np.r_[a + 20, b]]
    assert T.pick_main(frames) == [0, 1, None, 0]
    assert T.pick_main([np.r_[a, b]], seed=(0.9, 0.2), size=(800, 450)) == [1]


def test_time_formats():
    assert T.mmss(83.44) == "01:23.4"
    assert T.seconds("01:23.4") == pytest.approx(83.4)
    assert T.seconds("1:05") == 65


REVIEW = [
    {"reps": [
        {"id": "R001", "t": "00:05.0", "category": "shot", "zone": "ft", "result": "make"},
        {"id": "R002", "t": "00:10.0", "category": "finish", "type": "layup-left", "hand": "L", "result": "miss", "miss": "rim-out"},
        {"id": "R003", "t": "00:12.0", "category": "not_a_rep"},
        {"id": "R004", "t": "00:20.0", "category": "shot", "zone": "ft", "result": "make"},
    ]},
    {"reps": [{"id": "R005", "t": "00:40.0", "category": "shot", "zone": "mid", "result": "unclear"}],
     "added_reps": [{"id": "A01", "t": "00:30.0", "category": "shot", "zone": "ft", "result": "miss", "miss": "short", "added": True}]},
]


def test_aggregation():
    reps = T.reviewed_reps(REVIEW)
    assert [r["id"] for r in reps] == ["R001", "R002", "R004", "A01", "R005"]
    assert T.tally(reps) == dict(made=2, att=4, pct=0.5, unclear=1)
    zones = T.by([r for r in reps if r["category"] == "shot"], "zone", T.ZONES)
    assert list(zones) == ["ft", "mid"] and zones["ft"] == dict(made=2, att=3, pct=0.667, unclear=0)
    assert T.longest_streak(reps) == 1
    th = T.thirds(reps, 0, 45)
    assert [x["att"] for x in th] == [2, 1, 1]  # 5 10 | 20 | 30 (40 unclear)


def test_check_targets():
    reps = T.reviewed_reps(REVIEW)
    got = T.check_targets([
        {"name": "FT 60%", "match": {"zone": "ft"}, "attempts": 3, "pct": 0.6},
        {"name": "left layups", "match": {"type": "layup-left"}, "attempts": 10, "pct": 0.5},
        {"name": "threes", "match": {"zone": "three"}, "attempts": 20},
    ], reps)
    assert [g["status"] for g in got] == ["met", "missed", "not_trained"]
    assert got[0]["actual_pct"] == 0.667


def test_form_stats_split_by_result():
    reps = [{"result": "make", "knee_bend": 40}, {"result": "make", "knee_bend": 50}, {"result": "miss", "knee_bend": 20},
            {"result": "miss", "knee_bend": None}]
    f = T.form_stats(reps)["knee_bend"]
    assert (f["n"], f["make_mean"], f["miss_mean"]) == (3, 45.0, 20.0)


def test_session_paths(tmp_path, monkeypatch):
    monkeypatch.setenv("HOOP_WORKSPACE", str(tmp_path))
    root = T.sessions_root("17")
    assert root == tmp_path / "players" / "17" / "training"
    assert T.session_name("17", "2026-10-20") == "2026-10-20"
    for name in ("2026-10-13", "2026-10-20"):
        (root / name).mkdir(parents=True)
        (root / name / "session.json").write_text("{}")
    assert T.session_name("17", "2026-10-20") == "2026-10-20-2"
    (root / "notes").mkdir()
    assert [p.name for p in T.earlier_sessions(root / "2026-10-20")] == ["2026-10-13"]
    assert T.media_root_for("17", {"media_root": str(tmp_path / "m")}) == tmp_path / "m" / "players" / "17" / "training"


def test_load_game_finds_session_json(tmp_path):
    from hoop_tape_miner import game_config as gc
    (tmp_path / "session.json").write_text(json.dumps({"kind": "training", "video": "v.mp4"}))
    g = gc.load_game(tmp_path)
    assert gc.is_training(g) and g["video"] == "v.mp4"


def _person(x: float, y: float, s: float = 100.0) -> np.ndarray:
    """COCO-17 keypoints of a standing person, top of the head at (x, y), s = height in px."""
    kp = np.zeros((17, 2))
    kp[:5] = [x, y + 0.06 * s]
    kp[[T.L_SH, T.R_SH]] = [[x + 0.12 * s, y + 0.2 * s], [x - 0.12 * s, y + 0.2 * s]]
    kp[[T.L_EL, T.R_EL, T.L_WR, T.R_WR]] = [x, y + 0.4 * s]
    kp[[T.L_HIP, T.R_HIP]] = [[x + 0.08 * s, y + 0.5 * s], [x - 0.08 * s, y + 0.5 * s]]
    kp[[T.L_KN, T.R_KN]] = [[x + 0.08 * s, y + 0.75 * s], [x - 0.08 * s, y + 0.75 * s]]
    kp[[T.L_AN, T.R_AN]] = [[x + 0.08 * s, y + 0.95 * s], [x - 0.08 * s, y + 0.95 * s]]
    return kp



def test_pick_ball_carrier_moves_to_whoever_holds_the_ball():
    box = lambda x: np.array([x, 100, x + 60, 300], float)
    kp = lambda x: np.tile([x + 30, 200], (17, 1)).astype(float)  # wrists at the box centre
    cf = np.ones((2, 17))
    frames = [np.array([box(100), box(300)])] * 4
    kps = [np.array([kp(100), kp(300)])] * 4
    no_ball = np.zeros((0, 2))
    balls = [no_ball, np.array([[330, 205]]), no_ball, np.array([[130, 200], [330, 200]])]
    # start on the seed (left), the right one catches the ball, stays picked without a ball, both hold: no switch
    assert T.pick_ball_carrier(frames, kps, [cf] * 4, balls, seed=(0.1, 0.5), size=(800, 450)) == [0, 1, 1, 1]
    # no ball ever seen: the same as pick_main
    assert T.pick_ball_carrier(frames, kps, [cf] * 4, [no_ball] * 4) == T.pick_main(frames)
