"""Shot-attempt proposals from rim-scan blobs and their labels from a fake point chart, on synthetic data."""
import json

import numpy as np
import pandas as pd

from hoop_tape_miner import shots as S


def arc_rows(t0, side="right", fps=30, dur=0.6, u0=1.1, z0=4.2, gap=(), seed=0):
    """Blobs of a ball dropping into the rim: from (u0, z0) to the rim centre (0, 3.05) on a parabola."""
    rng = np.random.default_rng(seed)
    ts = np.arange(0, dur + 1e-9, 1 / fps)
    rows = []
    for i, s in enumerate(ts / dur):
        if i in gap:
            continue
        u = u0 * (1 - s) + rng.normal(0, 0.02)
        z = z0 + (3.05 - z0) * s ** 2 + 0.3 * s * (1 - s) + rng.normal(0, 0.02)
        rows.append(dict(frame=int((t0 + ts[i]) * 60), t=round(t0 + ts[i], 3), side=side, u=u, z=z, area=45))
    return rows


def noise_rows(t0, t1, side="right", fps=30, seed=1):
    """A static flicker (scoreboard digit) and random single-frame specks."""
    rng = np.random.default_rng(seed)
    rows = []
    for t in np.arange(t0, t1, 1 / fps):
        rows.append(dict(frame=int(t * 60), t=round(t, 3), side=side, u=-0.9, z=4.4, area=30))
        if rng.random() < 0.3:
            rows.append(dict(frame=int(t * 60), t=round(t, 3), side=side, u=rng.uniform(-1.2, 1.2),
                             z=rng.uniform(2.6, 4.6), area=25))
    return rows


def scan(*parts):
    return pd.DataFrame([r for p in parts for r in p]).sort_values("t").reset_index(drop=True)


def test_arc_with_gaps_becomes_one_proposal_noise_none():
    sc = scan(arc_rows(100.0, gap=(5, 6, 11)), noise_rows(95.0, 110.0))
    props = S.propose(sc)
    assert len(props) == 1
    p = props[0]
    assert p["side"] == "right" and 100.3 <= p["t"] <= 100.7 and p["d_rim"] < 0.2
    assert S.propose(scan(noise_rows(0.0, 60.0, seed=3))) == []


def test_two_quick_arcs_merge_and_sides_stay_apart():
    sc = scan(arc_rows(10.0), arc_rows(11.0, seed=2), arc_rows(10.2, side="left", u0=-1.0, seed=4),
              arc_rows(30.0, seed=5))
    props = S.propose(sc)
    assert [(p["side"], round(p["t"])) for p in props] == [("right", 11), ("left", 11), ("right", 31)] or \
        sorted((p["side"], round(p["t"])) for p in props) == [("left", 11), ("right", 11), ("right", 31)]
    assert [p["n_arcs"] for p in props if p["side"] == "right"][0] == 2


def test_arc_that_misses_the_rim_zone_is_not_a_proposal():
    far = [dict(r, u=r["u"] + 1.5) for r in arc_rows(50.0)]  # passes 1.5 m beside the hoop
    assert S.propose(scan(far)) == []


def flow(*events):
    return [dict(official_t=f"{i:02d}:00", our_video_t=t, team=team, points=pts, score_us=0, score_them=0)
            for i, (t, team, pts) in enumerate(events)]


def test_labels_come_from_the_point_chart_only():
    props = [dict(t=t, side="right", team=team) for t, team in
             ((100.0, "us"), (130.0, "us"), (140.0, "them"), (300.0, "us"), (400.0, "them"))]
    fl = flow((112.0, "us", 2),     # lag 12 s -> the 100 s attempt
              (150.0, "us", 3),     # latest same-team attempt in [110, 155] is 130
              (310.0, "them", 2),   # no "them" attempt in [270, 315]: CV missed it
              (900.0, "us", 1))     # free throw far from any attempt
    got, unmatched = S.label(props, fl)
    lab = {p["t"]: (p["label"], p["points"]) for p in got}
    assert lab == {100.0: ("made", 2), 130.0: ("made", 3), 140.0: ("likely miss", None),
                   300.0: ("likely miss", None), 400.0: ("likely miss", None)}
    assert [(e["our_video_t"], e["points"]) for e in unmatched] == [(310.0, 2), (900.0, 1)]
    ev = S.evaluate(got, unmatched, fl, None)
    assert ev["official_fg"] == 3 and ev["official_fg_matched"] == 2 and ev["official_fg_recall"] == 0.667
    assert ev["made"] == 2 and ev["likely_miss"] == 3


def test_lag_window_and_one_to_one():
    props = [dict(t=50.0, side="left", team=None)]
    got, unmatched = S.label(props, flow((95.0, "us", 2), (96.0, "us", 2)))
    assert got[0]["label"] == "likely miss" and len(unmatched) == 2  # 45 s before the feed: outside the window
    props = [dict(t=60.0, side="left", team=None)]
    got, unmatched = S.label(props, flow((70.0, "us", 2), (72.0, "us", 2)))
    assert got[0]["label"] == "made" and got[0]["team"] == "us" and len(unmatched) == 1


def test_attack_team_from_period_direction():
    poss = pd.DataFrame(dict(start=[0, 30, 1300, 1330], period=[1, 1, 2, 2], offence=["us", "them", "us", "them"],
                             side=["right", "left", "left", "right"]))
    from hoop_tape_miner.coach_features import attack_sides
    sides = attack_sides(poss)
    assert S.attack_team(20, "right", poss, sides) == "us"
    assert S.attack_team(1400, "right", poss, sides) == "them"
    assert S.attack_team(20, "right", None, {}) is None


def test_evaluate_against_review():
    props = [dict(t=101.0, side="right", label="made"), dict(t=205.0, side="right", label="likely miss"),
             dict(t=500.0, side="left", label="likely miss")]
    trips = [dict(t0=95, t1=103, result="made2", shot={"t": 100.0}),
             dict(t0=200, t1=210, result="missed"),
             dict(t0=300, t1=320, result="missed"),
             dict(t0=480, t1=495, result="turnover")]
    ev = S.evaluate(props, [], [], trips)
    assert ev["review_made_found"] == 1 and ev["review_missed_found"] == 1 and ev["review_missed_trips"] == 2
    assert ev["proposals_in_shot_trips"] == 2 and ev["proposals_outside_shot_trips"] == 1
    assert ev["made_label_in_reviewed_made_trip"] == 1


def test_cli_writes_proposals(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    scan(arc_rows(100.0), noise_rows(95.0, 110.0)).to_pickle(run / "rim_scan.pkl")
    pd.DataFrame(dict(start=[90.0], end=[105.0], period=[1], offence=["us"], side=["right"])).to_pickle(
        run / "possessions.pkl")
    (tmp_path / "official.json").write_text(json.dumps({"score_flow": flow((110.0, "us", 2))}))
    S.main(["--run", str(run), "--official", str(tmp_path / "official.json")])
    doc = json.loads((run / "shot_proposals.json").read_text())
    assert [(p["label"], p["points"], p["team"]) for p in doc["proposals"]] == [("made", 2, "us")]
    assert doc["evaluation"]["official_fg_recall"] == 1.0
    S.main(["--run", str(run), "--official", str(tmp_path / "missing.json"), "--out", str(tmp_path / "u.json")])
    assert json.loads((tmp_path / "u.json").read_text())["proposals"][0]["label"] == "unlabelled"
