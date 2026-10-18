"""Track features per trip (numbers back, spacing, ...) and ball-track quality / cleaning, on synthetic data."""
import json
import pickle

import numpy as np
import pandas as pd

from hoop_tape_miner import coach_features as F


def tracks_from(players: dict, t0=0.0, t1=5.0, fps=10):
    """players: {(team, track): fn(t) -> (x, y)} -> tracks DataFrame like tracks.pkl."""
    rows = []
    for i, t in enumerate(np.round(np.arange(t0, t1 + 1e-9, 1 / fps), 1)):
        for (team, tid), fn in players.items():
            p = fn(t)
            if p is None:
                continue
            x, y = p
            rows.append(dict(frame=i * 6, t=float(t), kind="person", team=team, track=tid,
                             cx=x, cy=y, cx_s=x, cy_s=y))
    return pd.DataFrame(rows)


def still(x, y):
    return lambda t: (x, y)


def test_numbers_back_counts_own_half():
    # 'us' attacks the right basket; 'them' defends it, so their own half is x > 14.
    players = {("us", i): still(20 + i, 3 + 2 * i) for i in range(5)}
    for i in range(3):  # three defenders back from the start
        players[("them", 10 + i)] = still(22 + i, 4 + 3 * i)
    # two defenders jog back: still in the far half at t=2 s
    players[("them", 20)] = lambda t: (5 + 2 * t, 7)
    players[("them", 21)] = lambda t: (2 + 2 * t, 9)
    tr = tracks_from(players)
    f = F.trip_features(tr, {"t0": 0.0, "t1": 5.0, "offence": "us"}, "right")
    assert f["numbers_back_2s"] == 3
    # the same scene mirrored: attacking left, the defenders' own half is x < 14
    mir = tr.assign(cx_s=28 - tr.cx_s, cx=28 - tr.cx)
    assert F.trip_features(mir, {"t0": 0.0, "t1": 5.0, "offence": "us"}, "left")["numbers_back_2s"] == 3
    # later offset: by t=5 s the joggers (x=15, 12) -> one more is back
    assert F.trip_features(tr, {"t0": 0.0, "t1": 5.0, "offence": "us"}, "right", back_offset=5.0)["numbers_back_2s"] == 4


def test_spacing_null_when_few_players():
    players = {("us", i): still(20 + 3 * i, 7) for i in range(2)}  # only 2 attackers tracked
    players.update({("them", 10 + i): still(22 + i, 4 + 3 * i) for i in range(5)})
    f = F.trip_features(tracks_from(players), {"t0": 0.0, "t1": 5.0, "offence": "us"}, "right")
    for k in ("off_spacing_m", "off_hull_m2", "paint_crowd", "standstill_share", "cross_half_s"):
        assert f[k] is None, k
    assert f["numbers_back_2s"] == 5  # the defence is still measurable
    players = {("us", i): still(20, 7) for i in range(5)}
    players[("them", 10)] = still(25, 7)
    f = F.trip_features(tracks_from(players), {"t0": 0.0, "t1": 5.0, "offence": "us"}, "right")
    assert f["numbers_back_2s"] is None and f["off_spacing_m"] is not None


def test_offence_shape_features():
    # four standing attackers on a 4 m square in the front court, one in the paint, one cutter at 2 m/s
    pts = [(18, 3), (22, 3), (18, 7), (22, 7)]
    players = {("us", i): still(*p) for i, p in enumerate(pts)}
    players[("us", 9)] = still(26, 7.5)  # in the right paint
    players[("us", 8)] = lambda t: (16, 2 + 2 * t)  # moving
    players.update({("them", 10 + i): still(23, 3 + 2 * i) for i in range(5)})
    f = F.trip_features(tracks_from(players), {"t0": 0.0, "t1": 5.0, "offence": "us"}, "right")
    assert f["paint_crowd"] == 1.0
    assert abs(f["standstill_share"] - 5 / 6) < 0.02
    assert f["cross_half_s"] == 0.0
    assert f["off_spacing_m"] > 2 and f["off_hull_m2"] > 16


def test_cross_half_time():
    players = {("us", i): (lambda i: lambda t: (8 + 3 * t, 2 + 3 * i))(i) for i in range(5)}  # x=14 at t=2
    players.update({("them", 10 + i): still(24, 3 + 2 * i) for i in range(5)})
    f = F.trip_features(tracks_from(players), {"t0": 0.0, "t1": 5.0, "offence": "us"}, "right")
    assert 2.0 <= f["cross_half_s"] <= 2.2


def balls(rows):
    return pd.DataFrame([dict(frame=f, t=round(f / 60, 3), kind="ball", x1=x - 10, y1=y - 10, x2=x + 10, y2=y + 10,
                              conf=c, cx=x / 50, cy=y / 50) for f, x, y, c in rows])


def test_clean_ball_picks_consistent_candidate():
    rows = []
    for i in range(20):  # true ball moving 20 px per 0.1 s, plus a jumping false positive in every 2nd frame
        rows.append((i * 6, 300 + 20 * i, 400, 0.55))
        if i % 2 == 0:
            rows.append((i * 6, 1000 - 300 * (i % 4), 100 + 30 * i, 0.6))
    c = F.clean_ball(balls(rows))
    assert c.frame.is_unique and len(c) == 20
    assert np.allclose((c.x1 + c.x2) / 2, 300 + 20 * np.arange(20))
    assert not c.interp.any()


def test_clean_ball_drops_static_and_unanchored_tracklets():
    rows = [(i * 6, 300 + 20 * i, 400, 0.55) for i in range(5)]  # real ball, 0.5 s
    rows += [(i * 6, 800, 100, 0.9) for i in range(5, 20)]  # confident but still on the court for 1.5 s (a bag)
    rows += [(i * 6, 300 + 20 * i, 600, 0.35) for i in range(20, 30)]  # moving but never confident
    b = balls(rows)
    b.loc[b.y1 == 90, "cx"] += np.linspace(0, 0.2, 15)  # projection jitter
    c = F.clean_ball(b)
    assert sorted(c.frame) == [i * 6 for i in range(5)]


def test_clean_ball_interpolates_short_gaps_only():
    rows = [(i * 6, 300 + 20 * i, 400, 0.5) for i in range(10) if i not in (4, 5)]  # 0.3 s gap
    rows += [(i * 6, 300 + 20 * i, 400, 0.5) for i in range(20, 25)]  # 1.0 s gap before this
    c = F.clean_ball(balls(rows))
    assert set(c.frame[c.interp]) == {24, 30}
    assert np.allclose(c.set_index("frame").loc[[24, 30], "x1"], [370, 390])
    assert not set(c.frame) & {i * 6 for i in range(10, 20)}


def test_ball_quality():
    persons = pd.DataFrame([dict(frame=i * 6, t=i / 10, kind="person", conf=0.9) for i in range(10)])
    b = balls([(0, 100, 100, 0.5), (0, 500, 100, 0.4), (6, 110, 100, 0.5), (24, 140, 100, 0.5), (54, 1, 1, 0.1)])
    q = F.ball_quality(pd.concat([persons, b]), 0.3)
    assert q["coverage"] == 0.3 and q["multi_share"] == round(1 / 3, 3)
    assert q["gap_p50"] == 0.1 or q["gap_p50"] == 0.2
    assert q["gap_p90"] <= 0.3


def test_ball_holder_nearest_box():
    tr = pd.DataFrame([dict(frame=0, t=0.0, team="us", track=1, x1=100, y1=100, x2=140, y2=200),
                       dict(frame=0, t=0.0, team="them", track=2, x1=300, y1=100, x2=340, y2=200),
                       dict(frame=6, t=0.1, team="them", track=2, x1=300, y1=100, x2=340, y2=200)])
    b = F.clean_ball(balls([(0, 145, 150, 0.6), (6, 700, 150, 0.6)]))
    h = F.ball_holder(b, tr)
    assert h.set_index("frame").loc[0, "team"] == "us"
    assert pd.isna(h.set_index("frame").loc[6, "team"])  # ball far from every player


def test_cli_writes_features_and_ball_quality(tmp_path):
    run = tmp_path / "run"
    review = run / "review_v1"
    review.mkdir(parents=True)
    players = {("us", i): still(20 + i, 3 + 2 * i) for i in range(5)}
    players.update({("them", 10 + i): still(22 + i, 4 + 2 * i) for i in range(5)})
    tr = tracks_from(players, 0, 10)
    tr.to_pickle(run / "tracks.pkl")
    balls([(i * 6, 300 + 10 * i, 400, 0.5) for i in range(30)]).to_pickle(run / "detections.pkl")
    poss = pd.DataFrame([dict(start=0.0, end=10.0, dur=10.0, side="right", period=1, offence="us", frames=[],
                              dist_signal=0.0)])
    poss.index.name = "pid"
    with open(run / "possessions.pkl", "wb") as fh:
        pickle.dump(poss, fh)
    (review / "coach_part1.json").write_text(json.dumps(
        [{"pid": 0, "trip": 1, "t0": 0.0, "t1": 10.0, "offence": "us"},
         {"pid": 0, "trip": 2, "t0": 5.0, "t1": 9.0, "offence": "them"}]), encoding="utf8")
    F.main(["--run", str(run), "--review", str(review)])
    feats = json.loads((review / "features.json").read_text(encoding="utf8"))
    assert feats["0-1"]["attack_side"] == "right" and feats["0-1"]["numbers_back_2s"] == 5
    assert feats["0-2"]["attack_side"] == "left"  # the other team attacks the other basket
    q = json.loads((review / "ball_quality.json").read_text(encoding="utf8"))
    assert {"raw", "clean"} <= set(q)


def test_project_balls_uses_box_bottom_centre():
    b = balls([(0, 100, 100, 0.6), (6, 200, 100, 0.6)])
    cam = {"frame": np.array([0, 6]), "H": np.stack([np.eye(3), 2 * np.eye(3)])}  # 2*I is the same homography
    p = F.project_balls(b, cam)
    assert np.allclose(p[["cx", "cy"]].to_numpy(), [[100, 110], [200, 110]])
