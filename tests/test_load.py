"""Per-stint load (distance, sprints, top speed) from synthetic court tracks."""
import json

import numpy as np
import pandas as pd

from hoop_tape_miner import load as L


def tracks_of(paths: dict, t0=0.0, t1=60.0, fps=10):
    """paths: {(team, number, track): fn(t) -> (x, y) | None} -> DataFrame like tracks.pkl (cx_s = cx)."""
    rows = []
    for i, t in enumerate(np.round(np.arange(t0, t1 + 1e-9, 1 / fps), 1)):
        for (team, num, tid), fn in paths.items():
            p = fn(t)
            if p is None:
                continue
            rows.append(dict(frame=i * 6, t=float(t), team=team, track=tid, number=num,
                             cx=p[0], cy=p[1], cx_s=p[0], cy_s=p[1]))
    return pd.DataFrame(rows)


def test_stint_distance_sprint_and_top_speed():
    tr = tracks_of({("us", "7", 1): lambda t: (2 + 0.1 * t, 5) if t <= 30 else (5 + 6 * (t - 30), 5) if t <= 32 else (17, 5)})
    s = L.player_series(tr, "us", "7")
    out = L.stint_load(s, 0, 60)
    assert out["minutes"] == 1.0
    assert out["coverage"] > 0.95 and out["low_coverage"] is False
    assert abs(out["distance_m"] - (3 + 12)) < 0.6
    assert out["sprints"] == 1
    assert 5.5 < out["top_speed"] <= 6.1
    assert 9 < out["hsd_m"] <= 12.5  # about the 2 s at 6 m/s


def test_identity_switch_jump_is_not_counted():
    # a jump of 10 m between two frames (another player's track) must not add distance or a sprint
    tr = tracks_of({("us", "7", 1): lambda t: (3, 5) if t < 20 else (13, 5)})
    out = L.stint_load(L.player_series(tr, "us", "7"), 0, 60)
    assert out["distance_m"] < 0.5
    assert out["sprints"] == 0
    assert out["top_speed"] < 1


def test_short_burst_is_not_a_sprint():
    # 0.3 s at 6 m/s is shorter than the minimum sprint duration
    tr = tracks_of({("us", "7", 1): lambda t: (3, 5) if t < 10 else (3 + 6 * (t - 10), 5) if t < 10.3 else (4.8, 5)})
    out = L.stint_load(L.player_series(tr, "us", "7"), 0, 30)
    assert out["sprints"] == 0


def test_gaps_are_never_filled_and_low_coverage_flagged():
    # tracked only 0-10 s of a 60 s stint, moving 1 m/s; after the gap 30 m further on
    tr = tracks_of({("us", "7", 1): lambda t: (1 + t, 5) if t <= 10 else (26, 5) if t >= 50 else None})
    out = L.stint_load(L.player_series(tr, "us", "7"), 0, 60)
    assert out["low_coverage"] is True
    assert abs(out["distance_m"] - 10) < 0.6  # the 15 m between 10 s and 50 s is not added
    assert out["coverage"] < 0.5


def test_ambiguous_frames_dropped():
    # two tracklets read as the same jersey at the same time: those frames say nothing about either
    tr = tracks_of({("us", "7", 1): lambda t: (3 + t * 0.2, 5), ("us", "7", 2): lambda t: (20, 10) if t < 5 else None},
                   t1=20)
    s = L.player_series(tr, "us", "7")
    assert s.t.min() >= 5.0
    assert L.stint_load(s, 0, 20)["distance_m"] < 3.5


def test_no_samples_gives_unknowns():
    out = L.stint_load(L.player_series(tracks_of({}), "us", "7"), 0, 60)
    assert out["distance_m"] is None and out["top_speed"] is None and out["sprints"] is None
    assert out["coverage"] == 0 and out["low_coverage"] is True


def test_game_load_from_lineup_and_json(tmp_path):
    tr = tracks_of({("us", "7", 1): lambda t: (2 + 0.5 * t, 5), ("them", "4", 2): lambda t: (20, 3)}, t1=40)
    lineup = {"us#7": [[0, 20], [25, 40]], "them#4": [[0, 40]], "us#9": [[0, 10]]}
    doc = L.game_load(tr, lineup)
    p = doc["players"]["us#7"]
    assert len(p["stints"]) == 2 and p["stints"][0]["t0"] == 0
    assert abs(p["total"]["distance_m"] - 17.5) < 1.0
    assert p["total"]["minutes"] == round(35 / 60, 2)
    assert doc["players"]["us#9"]["total"]["distance_m"] is None
    run = tmp_path / "run"
    run.mkdir()
    tr.to_pickle(run / "tracks.pkl")
    (run / "lineup.json").write_text(json.dumps(lineup))
    L.main(["--run", str(run), "--lineup", str(run / "lineup.json")])
    saved = json.loads((run / "load.json").read_text())
    assert saved["players"]["them#4"]["total"]["distance_m"] < 0.5
    assert saved["params"]["sprint_speed"] == L.SPRINT_SPEED


def test_player_table_html(tmp_path):
    doc = {"params": {}, "players": {"us#7": {"team": "us", "number": "7", "stints": [
        dict(t0=0, t1=300, minutes=5.0, tracked_minutes=4.0, coverage=0.8, low_coverage=False, distance_m=410.0,
             m_per_tracked_min=102.5, sprints=3, top_speed=6.2, hsd_m=55.0),
        dict(t0=400, t1=500, minutes=1.67, tracked_minutes=0.4, coverage=0.24, low_coverage=True, distance_m=30.0,
             m_per_tracked_min=75.0, sprints=0, top_speed=3.1, hsd_m=0.0)],
        "total": dict(minutes=6.67, tracked_minutes=4.4, coverage=0.66, distance_m=440.0, m_per_tracked_min=100.0,
                      sprints=3, top_speed=6.2, hsd_m=55.0)}}}
    h = L.table_html(doc, "7", "en")
    assert "05:00" in h and "410" in h and "low coverage" in h and "6.2" in h
    assert L.table_html(doc, "8", "en") == ""
    assert "跑动" in L.table_html(doc, "7", "zh")
